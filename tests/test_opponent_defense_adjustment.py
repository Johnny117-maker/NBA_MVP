import numpy as np
import pandas as pd

from src.player_model import (
    EFFICIENCY_FEATURES,
    MINUTES_FEATURES,
    PTS_DIRECT_FEATURES,
    VOLUME_FEATURES,
    PlayerModelBundle,
    _opponent_defense_factor,
    _rate_features,
    predict_from_features,
)


class ConstantPredictor:
    def __init__(self, value: float):
        self.value = value

    def predict(self, rows):
        return np.full(len(rows), self.value, dtype=float)


def test_opponent_defense_factor_increases_for_weaker_defense_and_is_capped():
    rows = pd.DataFrame({"opponent_def_rating": [130.0, 110.0, 95.0, 250.0, 0.0]})
    factors = _opponent_defense_factor(rows, league_avg_opponent_def_rating=110.0)

    assert factors[0] > factors[1] > factors[2]
    assert factors[1] == 1.0
    assert factors[3] == 1.10
    assert factors[4] == 0.90


def test_predict_from_features_applies_opponent_defense_to_points_only():
    # Modelo determinístico para testar a integração sem retreinar um modelo caro.
    feature_names = set(
        [*MINUTES_FEATURES, *VOLUME_FEATURES, *EFFICIENCY_FEATURES, *PTS_DIRECT_FEATURES]
    )
    feature_names.update(_rate_features("reb"))
    feature_names.update(_rate_features("ast"))
    feature_names.update(
        {
            "minutes_avg5", "minutes_avg10", "minutes_avg5_stint", "minutes_avg10_stint",
            "fga_per_min_avg10", "fta_per_min_avg10", "reb_per_min_avg3", "reb_per_min_avg5",
            "reb_per_min_avg10", "reb_per_min_avg5_stint", "reb_per_min_avg10_stint",
            "ast_per_min_avg3", "ast_per_min_avg5", "ast_per_min_avg10",
            "ast_per_min_avg5_stint", "ast_per_min_avg10_stint", "prev_season_games",
            "games_since_trade", "is_home", "rest_days", "opponent_def_rating",
        }
    )
    base = {name: 0.5 for name in feature_names}
    base.update(
        {
            "minutes_avg5": 30.0,
            "minutes_avg10": 30.0,
            "minutes_avg5_stint": 30.0,
            "minutes_avg10_stint": 30.0,
            "fga_per_min_avg10": 0.4,
            "fta_per_min_avg10": 0.1,
            "prev_season_pts_avg": 20.0,
            "prev_season_reb_avg": 5.0,
            "prev_season_ast_avg": 4.0,
            "prev_season_minutes_avg": 30.0,
            "prev_season_pts_per_min": 0.65,
            "prev_season_reb_per_min": 0.16,
            "prev_season_ast_per_min": 0.13,
            "prev_season_games": 30.0,
            "games_since_trade": 15.0,
            "is_home": 1,
            "rest_days": 2,
        }
    )
    rows = pd.DataFrame(
        [
            {**base, "opponent_def_rating": 130.0},
            {**base, "opponent_def_rating": 110.0},
            {**base, "opponent_def_rating": 95.0},
        ]
    )
    bundle = PlayerModelBundle(
        minutes_model=ConstantPredictor(30.0),
        fga_model=ConstantPredictor(0.4),
        ts_pct_model=ConstantPredictor(0.55),
        rate_models={"reb": ConstantPredictor(0.16), "ast": ConstantPredictor(0.13)},
        metrics={},
        residual_std={"minutes": 3.0, "pts": 4.0, "reb": 2.0, "ast": 2.0},
        league_avg_opponent_def_rating=110.0,
        direct_pts_model=ConstantPredictor(0.65),
    )

    predictions = predict_from_features(bundle, rows)
    assert predictions.loc[0, "pts"] > predictions.loc[1, "pts"] > predictions.loc[2, "pts"]
    assert predictions["reb"].nunique() == 1
    assert predictions["ast"].nunique() == 1
