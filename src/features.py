from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WIN_PCT = 0.5
DEFAULT_REST_DAYS = 3
ROLLING_WINDOW = 10

FEATURE_COLUMNS = ["off_rating", "def_rating", "net_rating", "last10_win_pct", "rest_days"]

_OUTPUT_COLUMNS = [
    "game_id",
    "game_date",
    "season",
    "home_team",
    "away_team",
    "home_off_rating",
    "away_off_rating",
    "home_def_rating",
    "away_def_rating",
    "home_net_rating",
    "away_net_rating",
    "home_last10_win_pct",
    "away_last10_win_pct",
    "home_rest_days",
    "away_rest_days",
    "home_points",
    "away_points",
    "home_win",
]


def _team_long_format(raw_games: pd.DataFrame, advanced_stats: pd.DataFrame | None) -> pd.DataFrame:
    """Uma linha por time por jogo, para calcular estatísticas móveis por time.

    `rating_for`/`rating_against` usam o Offensive/Defensive Rating oficial
    quando disponível em `advanced_stats` (game_id, team); senão, caem nos
    pontos marcados/sofridos daquele jogo (aproximação já usada antes).
    """
    home = raw_games.assign(
        team=raw_games["home_team"],
        points_for=raw_games["home_points"],
        points_against=raw_games["away_points"],
        is_home=True,
    )
    away = raw_games.assign(
        team=raw_games["away_team"],
        points_for=raw_games["away_points"],
        points_against=raw_games["home_points"],
        is_home=False,
    )
    long = pd.concat([home, away], ignore_index=True)
    long["win"] = (long["points_for"] > long["points_against"]).astype(int)

    if advanced_stats is not None and not advanced_stats.empty:
        official = advanced_stats[["game_id", "team", "off_rating", "def_rating"]].rename(
            columns={"off_rating": "official_off_rating", "def_rating": "official_def_rating"}
        )
        long = long.merge(official, on=["game_id", "team"], how="left")
    else:
        long["official_off_rating"] = np.nan
        long["official_def_rating"] = np.nan

    long["rating_for"] = long["official_off_rating"].fillna(long["points_for"])
    long["rating_against"] = long["official_def_rating"].fillna(long["points_against"])

    return long.sort_values(["team", "game_date"]).reset_index(drop=True)


def _per_team_rolling(group: pd.DataFrame) -> pd.DataFrame:
    """Calcula médias móveis usando apenas jogos anteriores (sem vazamento de dados)."""
    group = group.sort_values("game_date").copy()
    group["off_rating"] = (
        group["rating_for"].shift(1).rolling(ROLLING_WINDOW, min_periods=1).mean()
    )
    group["def_rating"] = (
        group["rating_against"].shift(1).rolling(ROLLING_WINDOW, min_periods=1).mean()
    )
    group["last10_win_pct"] = (
        group["win"].shift(1).rolling(ROLLING_WINDOW, min_periods=1).mean()
    )
    group["rest_days"] = (group["game_date"] - group["game_date"].shift(1)).dt.days
    return group


def _add_rolling_features(long: pd.DataFrame) -> pd.DataFrame:
    league_avg_rating = float(long["rating_for"].mean())

    long = long.groupby("team", group_keys=False).apply(
        _per_team_rolling, include_groups=False
    )
    long["off_rating"] = long["off_rating"].fillna(league_avg_rating)
    long["def_rating"] = long["def_rating"].fillna(league_avg_rating)
    long["last10_win_pct"] = long["last10_win_pct"].fillna(DEFAULT_WIN_PCT)
    long["rest_days"] = long["rest_days"].fillna(DEFAULT_REST_DAYS).astype(int)
    long["net_rating"] = long["off_rating"] - long["def_rating"]
    return long


def engineer_features(
    raw_games: pd.DataFrame, advanced_stats: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Transforma jogos brutos (data e placar) no formato usado pelo modelo.

    `off_rating`/`def_rating` usam o Offensive/Defensive Rating oficial da
    NBA quando `advanced_stats` traz esse jogo/time (ver
    `src/nba_client.py::fetch_game_advanced_stats`); caso contrário, caem na
    aproximação por pontos: a média móvel dos últimos 10 jogos de pontos
    marcados/sofridos. Todas as médias usam apenas jogos anteriores ao que
    está sendo previsto.
    """
    raw_games = raw_games.copy()
    raw_games["game_date"] = pd.to_datetime(raw_games["game_date"])

    long = _add_rolling_features(_team_long_format(raw_games, advanced_stats))

    home_features = (
        long.loc[long["is_home"], ["game_id", *FEATURE_COLUMNS]]
        .set_index("game_id")
        .add_prefix("home_")
    )
    away_features = (
        long.loc[~long["is_home"], ["game_id", *FEATURE_COLUMNS]]
        .set_index("game_id")
        .add_prefix("away_")
    )

    games = (
        raw_games.set_index("game_id").join(home_features).join(away_features).reset_index()
    )
    games["home_rest_days"] = games["home_rest_days"].astype(int)
    games["away_rest_days"] = games["away_rest_days"].astype(int)
    games["home_win"] = (games["home_points"] > games["away_points"]).astype(int)

    return games[_OUTPUT_COLUMNS].sort_values("game_date").reset_index(drop=True)
