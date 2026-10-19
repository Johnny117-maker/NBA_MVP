from __future__ import annotations

import numpy as np
import pandas as pd

from .player_metrics import player_season_summary

MIN_GAMES = 15
MIN_MINUTES = 10.0
MIN_MINUTES_FOR_RATE_AVERAGE = 5.0

HIGH_PERCENTILE = 70
LOW_PERCENTILE = 30

DIMENSION_WEIGHTS = {
    "efficiency_pct": 0.25,
    "creation_pct": 0.20,
    "defense_pct": 0.15,
    "rebounding_pct": 0.15,
    "consistency_pct": 0.15,
    "availability_pct": 0.10,
}

DIMENSION_LABELS = {
    "efficiency_pct": "Eficiência ofensiva",
    "creation_pct": "Criação de jogadas",
    "defense_pct": "Defesa (proxy)",
    "rebounding_pct": "Rebotes",
    "consistency_pct": "Consistência",
    "availability_pct": "Disponibilidade",
}


def _rate_averages(player_games: pd.DataFrame) -> pd.DataFrame:
    """Médias de AST%/REB% por jogador, ignorando jogos com poucos minutos
    (evita que um jogo de 1 minuto distorça a média com uma taxa extrema)."""
    meaningful = player_games[player_games["minutes"] >= MIN_MINUTES_FOR_RATE_AVERAGE]
    return meaningful.groupby("player_id").agg(
        ast_pct_mean=("ast_pct", "mean"),
        reb_pct_mean=("reb_pct", "mean"),
    )


def _shooting_profile(player_games: pd.DataFrame) -> pd.DataFrame:
    return player_games.groupby("player_id").agg(
        fg3a_mean=("fg3a", "mean"),
        fga_mean=("fga", "mean"),
    )


def qualified_players(player_games: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por jogador qualificado (mínimo de jogos e minutos), com as
    estatísticas usadas nas dimensões do NAPS e na classificação de estilo.
    """
    summary = player_season_summary(player_games).set_index("player_id")
    rates = _rate_averages(player_games)
    shooting = _shooting_profile(player_games)
    combined = summary.join(rates).join(shooting)
    combined["three_rate"] = combined["fg3a_mean"] / combined["fga_mean"].replace(0, np.nan)

    qualified = combined[
        (combined["games"] >= MIN_GAMES) & (combined["minutes_mean"] >= MIN_MINUTES)
    ].copy()
    return qualified.reset_index()


def _percentile(series: pd.Series) -> pd.Series:
    return series.rank(pct=True) * 100


def compute_percentiles(qualified: pd.DataFrame) -> pd.DataFrame:
    """Adiciona um percentil (0-100) por dimensão, dentro do grupo qualificado."""
    df = qualified.copy()

    df["efficiency_pct"] = pd.concat(
        [_percentile(df["true_shooting_pct_mean"]), _percentile(df["effective_fg_pct_mean"])],
        axis=1,
    ).mean(axis=1)
    df["creation_pct"] = pd.concat(
        [_percentile(df["ast_pct_mean"]), _percentile(df["ast_to_ratio_mean"])], axis=1
    ).mean(axis=1)
    df["defense_pct"] = _percentile(df["stl_per36_mean"] + df["blk_per36_mean"])
    df["rebounding_pct"] = _percentile(df["reb_pct_mean"])

    consistency_raw = 1 / df["pts_cv"].replace(0, np.nan)
    df["consistency_pct"] = _percentile(consistency_raw)
    df["availability_pct"] = _percentile(df["games"])

    # Percentis auxiliares, usados só na classificação de estilo (não entram no NAPS).
    df["usage_pct_pct"] = _percentile(df["usage_pct_mean"])
    df["three_rate_pct"] = _percentile(df["three_rate"])
    df["minutes_pct"] = _percentile(df["minutes_mean"])
    df["pts_per36_pct"] = _percentile(df["pts_per36_mean"])

    return df


def compute_naps(percentiles: pd.DataFrame) -> pd.Series:
    """NAPS = média ponderada dos percentis por dimensão, 0-100.

    Se uma dimensão faltar para um jogador (dados insuficientes), o peso dela
    é redistribuído entre as dimensões disponíveis daquele jogador.
    """
    dims = list(DIMENSION_WEIGHTS)
    weights = pd.Series(DIMENSION_WEIGHTS)

    values = percentiles[dims]
    available = values.notna()
    effective_weights = available.mul(weights, axis=1)
    weight_sums = effective_weights.sum(axis=1).replace(0, np.nan)
    return (values.fillna(0) * effective_weights).sum(axis=1) / weight_sums


def classify_style(row: pd.Series) -> str:
    """Classificação de estilo por regras (cascata), seção 4 do planejamento."""

    def high(column: str) -> bool:
        value = row[column]
        return pd.notna(value) and value >= HIGH_PERCENTILE

    def low(column: str) -> bool:
        value = row[column]
        return pd.notna(value) and value <= LOW_PERCENTILE

    if high("usage_pct_pct") and high("creation_pct"):
        return "Criador principal"
    if high("creation_pct"):
        return "Armador organizador"
    if high("three_rate_pct") and high("defense_pct"):
        return "Ala 3-and-D"
    if high("three_rate_pct") and high("efficiency_pct"):
        return "Especialista de três"
    if high("defense_pct") and high("rebounding_pct"):
        return "Protetor de aro"
    if high("usage_pct_pct") and high("efficiency_pct"):
        return "Pontuador eficiente"
    if high("usage_pct_pct"):
        return "Pontuador de volume"
    if high("rebounding_pct"):
        return "Reboteiro"
    if high("defense_pct"):
        return "Defensor de perímetro"
    if low("minutes_pct") and high("pts_per36_pct"):
        return "Reserva de impacto"
    return "Jogador versátil"


def build_player_index(player_games: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por jogador qualificado, com NAPS, percentis por dimensão e estilo."""
    qualified = qualified_players(player_games)
    if qualified.empty:
        return qualified.assign(naps=pd.Series(dtype=float), style=pd.Series(dtype=object))

    percentiles = compute_percentiles(qualified)
    percentiles["naps"] = compute_naps(percentiles)
    percentiles["style"] = percentiles.apply(classify_style, axis=1)
    return percentiles
