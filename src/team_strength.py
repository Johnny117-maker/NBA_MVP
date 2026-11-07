"""Força dos times por Elo com margem de vitória e regressão entre temporadas.

Por que existe: as médias de dez jogos (`features.py`) misturam o fim da temporada
anterior com o começo da atual e não corrigem a força dos adversários. No início
da temporada isso gera previsões instáveis. O Elo acumula todo o histórico, dá
mais peso a vitórias contra times fortes e a placares largos, e volta parcialmente
à média a cada nova temporada (elencos mudam).

Os parâmetros foram escolhidos só com as temporadas 2021-22 a 2023-24 e avaliados
em 2024-25, 2025-26 e na temporada atual, que não participaram da escolha. Veja
`docs/MODELO_TIMES_ELO.md`.

Tudo aqui é causal: o Elo de um jogo (`home_elo`/`away_elo`) usa apenas jogos
anteriores. Partidas da mesma data não se influenciam, porque cada time joga uma
vez por dia.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

ELO_BASE = 1500.0
ELO_K = 15.0
# Vantagem de mando usada só ao calcular a expectativa durante a atualização do
# Elo. No modelo, o efeito do mando fica no termo constante da regressão.
ELO_HOME_ADVANTAGE = 45.0
# Fração da distância até a média preservada na virada de temporada.
ELO_SEASON_CARRY = 0.6

_REQUIRED = ("game_date", "home_team", "away_team", "home_points", "away_points")


def season_key(dates) -> np.ndarray:
    """Ano de início da temporada NBA (agosto em diante pertence à nova temporada)."""
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    return np.where(index.month >= 8, index.year, index.year - 1)


def _regress(ratings: dict[str, float]) -> None:
    for team, rating in ratings.items():
        ratings[team] = ELO_BASE + ELO_SEASON_CARRY * (rating - ELO_BASE)


def elo_history(games: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict[str, float], int | None]:
    """Elo de cada jogo antes de ele acontecer, e o estado final.

    Devolve `(home_pre, away_pre, ratings, last_season)`. Os dois primeiros
    vetores seguem a ordem das linhas de `games`, mesmo que ele não esteja
    ordenado por data.
    """
    missing = [column for column in _REQUIRED if column not in games.columns]
    if missing:
        raise ValueError(f"Colunas ausentes para calcular o Elo: {', '.join(missing)}.")

    total = len(games)
    home_pre = np.full(total, ELO_BASE)
    away_pre = np.full(total, ELO_BASE)
    if total == 0:
        return home_pre, away_pre, {}, None

    dates = pd.to_datetime(games["game_date"]).to_numpy()
    order = np.argsort(dates, kind="stable")
    seasons = season_key(games["game_date"])
    home = games["home_team"].astype(str).to_numpy()
    away = games["away_team"].astype(str).to_numpy()
    home_points = pd.to_numeric(games["home_points"], errors="coerce").to_numpy(dtype=float)
    away_points = pd.to_numeric(games["away_points"], errors="coerce").to_numpy(dtype=float)

    ratings: dict[str, float] = {}
    last_season: int | None = None
    for position in order:
        season = int(seasons[position])
        if last_season is not None and season != last_season:
            _regress(ratings)
        last_season = season

        home_rating = ratings.get(home[position], ELO_BASE)
        away_rating = ratings.get(away[position], ELO_BASE)
        home_pre[position] = home_rating
        away_pre[position] = away_rating

        margin = home_points[position] - away_points[position]
        if not np.isfinite(margin) or margin == 0:
            continue
        difference = home_rating + ELO_HOME_ADVANTAGE - away_rating
        expected = 1.0 / (1.0 + 10.0 ** (-difference / 400.0))
        winner_difference = difference if margin > 0 else -difference
        # Placares largos contam mais, mas o favorito que vence por muito rende menos.
        multiplier = ((abs(margin) + 3.0) ** 0.8) / (7.5 + 0.006 * winner_difference)
        shift = ELO_K * multiplier * ((1.0 if margin > 0 else 0.0) - expected)
        ratings[home[position]] = home_rating + shift
        ratings[away[position]] = away_rating - shift
    return home_pre, away_pre, ratings, last_season


def current_elo_ratings(games: pd.DataFrame, as_of: date | None = None) -> dict[str, float]:
    """Elo atual de cada time, após todos os jogos de `games`.

    Se `as_of` cai numa temporada posterior à do último jogo (por exemplo, o
    primeiro jogo do ano), aplica a regressão de virada de temporada.
    """
    _, _, ratings, last_season = elo_history(games)
    if as_of is not None and last_season is not None and int(season_key([as_of])[0]) > last_season:
        ratings = dict(ratings)
        _regress(ratings)
    return ratings


def ensure_elo_columns(games: pd.DataFrame) -> pd.DataFrame:
    """Garante `home_elo`/`away_elo`. Bases já preparadas por `engineer_features` os trazem."""
    if {"home_elo", "away_elo"}.issubset(games.columns):
        return games
    home_pre, away_pre, _, _ = elo_history(games)
    enriched = games.copy()
    enriched["home_elo"] = home_pre
    enriched["away_elo"] = away_pre
    return enriched
