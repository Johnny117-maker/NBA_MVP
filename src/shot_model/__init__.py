"""Modelo de zonas de arremesso (participação e eficiência por zona).

O módulo foi dividido por responsabilidade; todos os nomes antigos continuam disponíveis
aqui, então `from src.shot_model import ...` segue funcionando.
"""

from .config import (  # noqa: F401
    MIN_GAMES_FOR_EFFICIENCY_MODEL,
    MIN_RESIDUAL_STD_FG_PCT,
    MIN_RESIDUAL_STD_SHARE,
    ZONE_FG_PCT_PRIOR,
    ZONE_SHARE_PRIOR,
    ZoneModelBundle,
)
from .evaluation import walk_forward_evaluate_zone_models  # noqa: F401
from .features import (  # noqa: F401
    _assign_zone_team_stints,
    _efficiency_features,
    _expanding_zone_defense,
    _per_player_zone_rolling,
    _regression_pipeline,
    _share_features,
    _team_zone_defense_games,
    add_opponent_zone_defense_features,
    add_zone_model_features,
    add_zone_rolling_features,
    build_zone_game_table,
)
from .prediction import (  # noqa: F401
    expected_fg_points,
    fill_missing_features_with_league_average,
    live_zone_snapshot,
    opponent_zone_defense_snapshot,
    predict_zone_distribution,
)
from .splits import split_zone_games_by_date, walk_forward_boundaries  # noqa: F401
from .training import train_zone_models  # noqa: F401
