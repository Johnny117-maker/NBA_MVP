from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WIN_PCT = 0.5
DEFAULT_REST_DAYS = 3
ROLLING_WINDOW = 10
DEFAULT_RATING = 110.0

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
    "home_observed_off_rating",
    "away_observed_off_rating",
    "home_observed_def_rating",
    "away_observed_def_rating",
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
    long["observed_off_rating"] = long["rating_for"]
    long["observed_def_rating"] = long["rating_against"]

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


def pregame_scoring_averages(games: pd.DataFrame) -> pd.DataFrame:
    """Média dos últimos dez placares por time, excluindo a data da previsão.

    Aceita também bases demonstrativas/CSV sem game_id. As posições preservam
    a ordem e o índice recebidos, mesmo quando há vários jogos na mesma data.
    """
    rows = []
    for side in ("home", "away"):
        rows.append(
            pd.DataFrame({
                "row": np.arange(len(games)),
                "side": side,
                "team": games[f"{side}_team"].to_numpy(),
                "game_date": pd.to_datetime(games["game_date"]).dt.normalize().to_numpy(),
                "points": games[f"{side}_points"].to_numpy(),
            })
        )
    long = pd.concat(rows, ignore_index=True).sort_values(
        ["team", "game_date", "row"], kind="stable"
    )
    long["average"] = long.groupby("team")["points"].transform(
        lambda values: values.shift(1).rolling(ROLLING_WINDOW, min_periods=1).mean()
    )
    # Todos os confrontos de um time na mesma data recebem o contexto anterior
    # ao primeiro deles; nenhum placar do próprio dia entra nas variáveis.
    prior_by_day = long.drop_duplicates(["team", "game_date"])[
        ["team", "game_date", "average"]
    ]
    long = long.drop(columns="average").merge(
        prior_by_day, on=["team", "game_date"], how="left", validate="many_to_one"
    )
    return pd.DataFrame(
        {
            f"{side}_points_avg10": long.loc[long["side"].eq(side)]
            .sort_values("row")["average"].fillna(DEFAULT_RATING).to_numpy()
            for side in ("home", "away")
        },
        index=games.index,
    )


def _add_rolling_features(long: pd.DataFrame) -> pd.DataFrame:
    long = long.groupby("team", group_keys=False).apply(
        _per_team_rolling, include_groups=False
    )
    # Um prior fixo não muda quando jogos futuros são acrescentados à base.
    long["off_rating"] = long["off_rating"].fillna(DEFAULT_RATING)
    long["def_rating"] = long["def_rating"].fillna(DEFAULT_RATING)
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
    context_columns = ["game_id", *FEATURE_COLUMNS, "observed_off_rating", "observed_def_rating"]

    home_features = (
        long.loc[long["is_home"], context_columns]
        .set_index("game_id")
        .add_prefix("home_")
    )
    away_features = (
        long.loc[~long["is_home"], context_columns]
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
