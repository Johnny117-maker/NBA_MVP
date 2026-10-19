from __future__ import annotations

import numpy as np
import pandas as pd

from .player_features import EMA_HALFLIFE_FAST, EMA_HALFLIFE_SLOW, effective_starter_flag

PER36_STATS = ["pts", "reb", "ast", "stl", "blk", "tov"]

_SUMMARY_STATS = ["pts", "reb", "ast", "stl", "blk", "tov"]
_EFFICIENCY_MEAN_COLUMNS = [
    "true_shooting_pct",
    "effective_fg_pct",
    "usage_pct",
    "ast_to_ratio",
]


def estimate_team_game_totals(player_games: pd.DataFrame) -> pd.DataFrame:
    """Totais de time por jogo, obtidos somando o boxscore de todos os jogadores.

    Aproximação: eventos só de equipe (ex.: alguns turnovers de time) não são
    atribuídos a nenhum jogador e por isso não entram nessa soma.
    """
    return player_games.groupby(["game_id", "team"], as_index=False).agg(
        team_minutes=("minutes", "sum"),
        team_fga=("fga", "sum"),
        team_fta=("fta", "sum"),
        team_tov=("tov", "sum"),
        team_fgm=("fgm", "sum"),
        team_reb=("reb", "sum"),
    )


def add_efficiency_metrics(player_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona TS%, eFG%, AST/TO e USG% por linha (jogador em um jogo)."""
    df = player_games.copy()

    ts_denominator = 2 * (df["fga"] + 0.44 * df["fta"])
    df["true_shooting_pct"] = np.where(
        ts_denominator > 0, df["pts"] / ts_denominator, np.nan
    )
    df["effective_fg_pct"] = np.where(
        df["fga"] > 0, (df["fgm"] + 0.5 * df["fg3m"]) / df["fga"], np.nan
    )
    df["ast_to_ratio"] = np.where(df["tov"] > 0, df["ast"] / df["tov"], np.nan)

    totals = estimate_team_game_totals(df)
    merged = df.merge(totals, on=["game_id", "team"], how="left")
    usage_numerator = (merged["fga"] + 0.44 * merged["fta"] + merged["tov"]) * (
        merged["team_minutes"] / 5
    )
    usage_denominator = merged["minutes"] * (
        merged["team_fga"] + 0.44 * merged["team_fta"] + merged["team_tov"]
    )
    df["usage_pct"] = np.where(
        usage_denominator > 0, 100 * usage_numerator / usage_denominator, np.nan
    )
    return df


def add_advanced_rate_metrics(player_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona AST% e REB% (fórmulas oficiais), usando os totais do próprio
    time e do adversário no mesmo jogo.

    Como a coleta traz o boxscore de todos os jogadores de ambos os times,
    os totais do adversário também podem ser somados (mesma lógica de
    `estimate_team_game_totals`, buscada pela coluna `opponent`).
    """
    df = player_games.copy()
    totals = estimate_team_game_totals(df)

    df = df.merge(totals, on=["game_id", "team"], how="left")

    opponent_totals = totals.rename(
        columns={
            "team": "opponent",
            "team_minutes": "opp_minutes",
            "team_fga": "opp_fga",
            "team_fta": "opp_fta",
            "team_tov": "opp_tov",
            "team_fgm": "opp_fgm",
            "team_reb": "opp_reb",
        }
    )
    df = df.merge(opponent_totals, on=["game_id", "opponent"], how="left")

    team_possession_factor = df["team_minutes"] / 5
    ast_denominator = (
        df["minutes"] / team_possession_factor.replace(0, np.nan)
    ) * df["team_fgm"] - df["fgm"]
    df["ast_pct"] = np.where(ast_denominator > 0, 100 * df["ast"] / ast_denominator, np.nan)

    reb_denominator = df["minutes"] * (df["team_reb"] + df["opp_reb"])
    df["reb_pct"] = np.where(
        reb_denominator > 0,
        100 * df["reb"] * team_possession_factor / reb_denominator,
        np.nan,
    )

    return df.drop(
        columns=[
            "team_minutes",
            "team_fga",
            "team_fta",
            "team_tov",
            "team_fgm",
            "team_reb",
            "opp_minutes",
            "opp_fga",
            "opp_fta",
            "opp_tov",
            "opp_fgm",
            "opp_reb",
        ]
    )


def add_per36_rates(player_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona estatísticas normalizadas para 36 minutos em quadra."""
    df = player_games.copy()
    scale = np.where(df["minutes"] > 0, 36 / df["minutes"], 0.0)
    for stat in PER36_STATS:
        df[f"{stat}_per36"] = df[stat] * scale
    return df


def list_players(player_games: pd.DataFrame) -> pd.DataFrame:
    """Jogador, time mais recente e quantidade de jogos, para preencher seletores."""
    ordered = player_games.sort_values("game_date")
    latest = ordered.groupby("player_id").agg(
        player_name=("player_name", "last"),
        team=("team", "last"),
        games=("game_id", "count"),
    )
    return latest.reset_index().sort_values("player_name").reset_index(drop=True)


def player_snapshot(player_games: pd.DataFrame, player_id, window: int = 10) -> dict:
    """Estado atual de um jogador (médias exponenciais, sem shift).

    Usado para prever um jogo genuinamente futuro — diferente das médias
    exponenciais de treino (`src/player_features.py`), que usam `shift` para
    não vazar dados de jogos passados durante a avaliação do modelo. Mesma
    meia-vida (`EMA_HALFLIFE_FAST`/`EMA_HALFLIFE_SLOW`) dos dois lados, para
    o modelo ver em previsão ao vivo o mesmo tipo de número que viu no
    treino.

    `window` só limita o quanto o histórico é olhado para trás (jogos muito
    antigos já pesam pouco na média exponencial de qualquer forma); não é
    mais uma janela flat.

    Além das médias de carreira, calcula as mesmas médias restritas à
    passagem (stint) atual do jogador pelo time — a sequência mais recente
    de jogos consecutivos pelo mesmo time, mesmo conceito de
    `src/player_features.py::assign_team_stints` — e `games_since_trade`,
    quantos jogos já foram disputados nessa passagem.
    """
    player_games = player_games.assign(
        _effective_starter=effective_starter_flag(player_games).astype(float)
    )
    full_history = player_games[player_games["player_id"] == player_id].sort_values("game_date")
    if full_history.empty:
        raise ValueError(f"Não há jogos para o jogador {player_id!r}.")
    history = full_history.tail(max(window * 5, window))

    def _ema(frame: pd.DataFrame, column: str, halflife: float) -> float:
        if frame.empty:
            return 0.0
        value = frame[column].ewm(halflife=halflife, min_periods=1).mean().iloc[-1]
        return float(value) if pd.notna(value) else 0.0

    def _rate(frame: pd.DataFrame, stat: str, halflife: float) -> float:
        valid = frame[frame["minutes"] > 0]
        if valid.empty:
            return 0.0
        ratio = valid[stat] / valid["minutes"]
        return float(ratio.ewm(halflife=halflife, min_periods=1).mean().iloc[-1])

    current_team = full_history.iloc[-1]["team"]
    stint_length = 0
    for _, row in full_history.iloc[::-1].iterrows():
        if row["team"] != current_team:
            break
        stint_length += 1
    stint_tail = full_history.tail(stint_length)

    snapshot = {
        "minutes_avg5": _ema(history, "minutes", EMA_HALFLIFE_FAST),
        "minutes_avg10": _ema(history, "minutes", EMA_HALFLIFE_SLOW),
        "pts_per_min_avg10": _rate(history, "pts", EMA_HALFLIFE_SLOW),
        "reb_per_min_avg10": _rate(history, "reb", EMA_HALFLIFE_SLOW),
        "ast_per_min_avg10": _rate(history, "ast", EMA_HALFLIFE_SLOW),
        "fga_per_min_avg10": _rate(history, "fga", EMA_HALFLIFE_SLOW),
        "fta_per_min_avg10": _rate(history, "fta", EMA_HALFLIFE_SLOW),
        "ts_pct_avg10": _ema(history, "true_shooting_pct", EMA_HALFLIFE_SLOW),
        "usg_pct_avg10": _ema(history, "usage_pct", EMA_HALFLIFE_SLOW),
        "starter_rate_avg10": _ema(history, "_effective_starter", EMA_HALFLIFE_SLOW),
        "minutes_avg5_stint": _ema(stint_tail, "minutes", EMA_HALFLIFE_FAST),
        "minutes_avg10_stint": _ema(stint_tail, "minutes", EMA_HALFLIFE_SLOW),
        "pts_per_min_avg10_stint": _rate(stint_tail, "pts", EMA_HALFLIFE_SLOW),
        "reb_per_min_avg10_stint": _rate(stint_tail, "reb", EMA_HALFLIFE_SLOW),
        "ast_per_min_avg10_stint": _rate(stint_tail, "ast", EMA_HALFLIFE_SLOW),
        "fga_per_min_avg10_stint": _rate(stint_tail, "fga", EMA_HALFLIFE_SLOW),
        "fta_per_min_avg10_stint": _rate(stint_tail, "fta", EMA_HALFLIFE_SLOW),
        "ts_pct_avg10_stint": _ema(stint_tail, "true_shooting_pct", EMA_HALFLIFE_SLOW),
        "usg_pct_avg10_stint": _ema(stint_tail, "usage_pct", EMA_HALFLIFE_SLOW),
        "starter_rate_avg10_stint": _ema(stint_tail, "_effective_starter", EMA_HALFLIFE_SLOW),
        "games_since_trade": float(stint_length),
        "games": float(len(full_history)),
    }

    # Janelas curtas ajudam a captar mudanças recentes sem descartar a média
    # exponencial de carreira. A janela conta partidas, incluindo linhas com
    # minutos zero; taxas ignoram apenas denominadores inválidos dentro dela.
    for window in (3, 5, 10):
        recent = history.tail(window)
        snapshot[f"pts_avg{window}"] = float(recent["pts"].mean()) if not recent.empty else 0.0

    def _recent_rate(frame: pd.DataFrame, stat: str, window: int) -> float:
        recent = frame.tail(window)
        valid = recent[recent["minutes"] > 0]
        if valid.empty:
            return 0.0
        values = (valid[stat] / valid["minutes"]).mean()
        return float(values) if pd.notna(values) else 0.0

    for stat in ("pts", "reb", "ast", "fga", "fta"):
        for window in (3, 5):
            snapshot[f"{stat}_per_min_avg{window}"] = _recent_rate(history, stat, window)
            snapshot[f"{stat}_per_min_avg{window}_stint"] = _recent_rate(
                stint_tail, stat, window
            )

    for window in (3, 5):
        for frame, suffix in ((history, ""), (stint_tail, "_stint")):
            ts_values = frame.tail(window)["true_shooting_pct"].dropna()
            usage_values = frame.tail(window)["usage_pct"].dropna()
            snapshot[f"ts_pct_avg{window}{suffix}"] = (
                float(ts_values.mean()) if not ts_values.empty else snapshot[f"ts_pct_avg10{suffix}"]
            )
            if window == 5:
                snapshot[f"usg_pct_avg5{suffix}"] = (
                    float(usage_values.mean())
                    if not usage_values.empty
                    else snapshot[f"usg_pct_avg10{suffix}"]
                )

    return snapshot


def player_season_summary(player_games: pd.DataFrame) -> pd.DataFrame:
    """Produção, eficiência e consistência por jogador.

    Requer que `player_games` já tenha passado por `add_efficiency_metrics`
    e `add_per36_rates`.
    """
    ordered = player_games.sort_values("game_date")
    grouped = ordered.groupby("player_id")

    summary = grouped.agg(
        player_name=("player_name", "last"),
        team=("team", "last"),
        games=("game_id", "count"),
        minutes_mean=("minutes", "mean"),
    )

    for stat in _SUMMARY_STATS:
        summary[f"{stat}_mean"] = grouped[stat].mean()
        summary[f"{stat}_median"] = grouped[stat].median()
        summary[f"{stat}_std"] = grouped[stat].std()
        summary[f"{stat}_cv"] = summary[f"{stat}_std"] / summary[f"{stat}_mean"].replace(0, np.nan)
        summary[f"{stat}_p25"] = grouped[stat].quantile(0.25)
        summary[f"{stat}_p75"] = grouped[stat].quantile(0.75)
        summary[f"{stat}_per36_mean"] = grouped[f"{stat}_per36"].mean()

    for column in _EFFICIENCY_MEAN_COLUMNS:
        summary[f"{column}_mean"] = grouped[column].mean()

    return summary.reset_index()


def compare_players(player_games: pd.DataFrame, player_ids: list) -> pd.DataFrame:
    """Tabela comparativa (jogadores em colunas) para 2 a 4 jogadores."""
    subset = player_games[player_games["player_id"].isin(player_ids)]
    summary = player_season_summary(subset).set_index("player_name")

    columns = [
        "team",
        "games",
        "minutes_mean",
        "pts_mean",
        "reb_mean",
        "ast_mean",
        "stl_mean",
        "blk_mean",
        "true_shooting_pct_mean",
        "effective_fg_pct_mean",
        "usage_pct_mean",
        "ast_to_ratio_mean",
        "pts_per36_mean",
        "reb_per36_mean",
        "ast_per36_mean",
    ]
    return summary[columns].T
