"""Constantes de características e estruturas de dados do modelo de jogadores."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline

SEASON_BASELINE_FEATURES = [
    "prev_season_pts_avg",
    "prev_season_reb_avg",
    "prev_season_ast_avg",
    "prev_season_minutes_avg",
    "prev_season_pts_per_min",
    "prev_season_reb_per_min",
    "prev_season_ast_per_min",
    "prev_season_games",
]

MINUTES_FEATURES = [
    "minutes_avg5",
    "minutes_avg10",
    "minutes_avg5_stint",
    "minutes_avg10_stint",
    "starter_rate_avg10",
    "starter_rate_avg10_stint",
    "games_since_trade",
    "rest_days",
    "is_back_to_back",
    "is_long_rest",
    "is_home",
    "prev_season_minutes_avg",
    "prev_season_games",
]

# Janelas curtas captam mudanças de função/volume, enquanto as EMAs de 10
# jogos estabilizam o sinal. A cadeia volume × eficiência é mantida como
# referência interpretável; a projeção central também testa um regressor direto.
VOLUME_FEATURES = [
    "fga_per_min_avg3",
    "fga_per_min_avg5",
    "fga_per_min_avg10",
    "fga_per_min_avg5_stint",
    "fga_per_min_avg10_stint",
    "fta_per_min_avg3",
    "fta_per_min_avg5",
    "fta_per_min_avg10",
    "usg_pct_avg5",
    "usg_pct_avg10",
    "usg_pct_avg5_stint",
    "usg_pct_avg10_stint",
    "games_since_trade",
    "rest_days",
    "is_back_to_back",
    "is_long_rest",
    "is_home",
    "prev_season_pts_avg",
    "prev_season_pts_per_min",
    "prev_season_minutes_avg",
    "prev_season_games",
]
EFFICIENCY_FEATURES = [
    "ts_pct_avg3",
    "ts_pct_avg5",
    "ts_pct_avg10",
    "ts_pct_avg3_stint",
    "ts_pct_avg5_stint",
    "ts_pct_avg10_stint",
    "pts_per_min_avg3",
    "pts_per_min_avg5",
    "pts_per_min_avg10",
    "pts_per_min_avg5_stint",
    "opponent_def_rating",
    "rest_days",
    "is_back_to_back",
    "is_long_rest",
    "is_home",
    "prev_season_pts_avg",
    "prev_season_pts_per_min",
    "prev_season_minutes_avg",
    "prev_season_games",
]

# Rebotes e assistências continuam como taxa direta (produção por minuto) —
# a decomposição em volume/eficiência é específica de pontos.
SIMPLE_RATE_STATS = ["reb", "ast"]

# Modelo alternativo de pontos por minuto: inclui oportunidade (minutos,
# titularidade/rotação), volume, eficiência e contexto pré-jogo.
PTS_DIRECT_FEATURES = list(
    dict.fromkeys(
        [*MINUTES_FEATURES, *VOLUME_FEATURES, *EFFICIENCY_FEATURES, *SEASON_BASELINE_FEATURES]
    )
)

# No modo quantile, os limites usam a mesma família de características do
# modelo direto. Evita quantis compostos de modelos diferentes (FGA × TS%).
PTS_QUANTILE_FEATURES = list(PTS_DIRECT_FEATURES)

QUANTILE_ALPHAS = {"p10": 0.1, "p50": 0.5, "p90": 0.9}

MIN_RESIDUAL_STD_MINUTES = 3.0
MIN_RESIDUAL_STD_STAT = 1.5


@dataclass
class PlayerModelBundle:
    minutes_model: Pipeline
    fga_model: Pipeline
    ts_pct_model: Pipeline
    rate_models: dict
    metrics: dict
    residual_std: dict
    league_avg_opponent_def_rating: float
    direct_pts_model: HistGradientBoostingRegressor | None = None
    interval_method: str = "normal"
    quantile_rate_models: dict | None = None


@dataclass(frozen=True)
class PlayerGamePrediction:
    minutes: float
    stats: dict
    stats_low: dict
    stats_high: dict
    confidence: str
    projected_fga: float
    projected_ts_pct: float
    chain_pts: float
