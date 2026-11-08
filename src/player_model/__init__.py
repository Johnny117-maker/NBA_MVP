"""Modelos de projeção de jogadores (minutos, pontos, rebotes e assistências).

O módulo foi dividido por responsabilidade; todos os nomes antigos continuam
disponíveis aqui, então `from src.player_model import ...` segue funcionando.
"""

from .config import (  # noqa: F401
    EFFICIENCY_FEATURES,
    MIN_RESIDUAL_STD_MINUTES,
    MIN_RESIDUAL_STD_STAT,
    MINUTES_FEATURES,
    PTS_DIRECT_FEATURES,
    PTS_QUANTILE_FEATURES,
    QUANTILE_ALPHAS,
    SEASON_BASELINE_FEATURES,
    SIMPLE_RATE_STATS,
    VOLUME_FEATURES,
    PlayerGamePrediction,
    PlayerModelBundle,
)
from .evaluation import (  # noqa: F401
    _aggregate_folds,
    _fold_boundaries,
    _fold_metrics,
    _fold_prediction_records,
    walk_forward_evaluate,
)
from .prediction import (  # noqa: F401
    _bucket_cdf,
    _normal_cdf,
    _predict_intervals,
    over_probability,
    predict_from_features,
    predict_player_game,
    range_probabilities,
)
from .preparation import (  # noqa: F401
    _blend_season_baseline,
    _calibrate_minutes_predictions,
    _direct_points_regressor,
    _fit_quantile_models,
    _fta_per_fga_ratio,
    _opponent_defense_factor,
    _prediction_confidence,
    _prepare,
    _quantile_pipeline,
    _rate_features,
    _regression_pipeline,
    _season_baseline_weight,
    _temporal_train_test_split,
)
from .training import (  # noqa: F401
    _evaluate_minutes,
    _evaluate_points,
    _evaluate_rate_stats,
    _fit_final_models,
    train_player_models,
)
