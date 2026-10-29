import numpy as np
import pandas as pd

from src.minutes_model import MINUTE_FEATURES, project_minutes, train_minutes


def sample():
    rows = []
    for day in pd.date_range("2026-08-01", periods=40):
        for player in range(40):
            base = 10 + player * 0.5
            rows.append(
                dict(
                    game_date=day,
                    minutes=base * 0.5 + 12,
                    expected_minutes=base,
                    minutes_3=base,
                    minutes_5=base,
                    minutes_10=base,
                    minutes_std10=2,
                    minutes_trend=0,
                    rest=2,
                    is_home=player % 2,
                    history_games=10,
                    usage_10=20,
                )
            )
    return pd.DataFrame(rows)


def test_minutes_model_requires_temporal_gain_and_guard_on_player_projections():
    table = sample()
    fit = table.loc[table.game_date.lt("2026-08-25")]
    cal = table.loc[table.game_date.between("2026-08-25", "2026-09-01")]
    test = table.loc[table.game_date.gt("2026-09-01")]
    model, report = train_minutes(fit, cal, test, table, {}, estimators=80)
    assert report["fit_end"] < report["calibration_start"] < report["validation_start"]
    assert report["active"] and report["candidate_mae"] < report["base_mae"]
    result = project_minutes(table.iloc[-1], model, report)
    assert 0 <= result["low"] <= result["projected"] <= result["high"] <= 48
    test = test.assign(pts=20.0)
    _, guarded = train_minutes(fit, cal, test, table, {"pts": np.full(len(test), 20.0)}, estimators=80)
    assert not guarded["active"] and guarded["weight"] == 0


def test_sparse_minutes_history_falls_back_without_claiming_a_lineup():
    class Forbidden:
        def predict(self, frame):
            raise AssertionError("Amostra curta não deve aplicar o modelo de minutos")

    result = project_minutes(
        pd.Series({"expected_minutes": 24.0, "history_games": 3}), Forbidden(), {"active": True, "weight": 1}
    )
    assert result["projected"] == 24
    assert "não confirmados" in result["participation"]


def test_minute_features_exclude_the_same_and_future_games():
    from src.player_data import generate_demo_player_games
    from src.prop_training import feature_table

    history = (
        generate_demo_player_games(games_per_team=10)
        .sort_values("game_date")
        .drop_duplicates(["player_id", "game_date"])
        .copy()
    )
    original = feature_table(history)
    day = history.game_date.quantile(0.7)
    changed = history.copy()
    changed.loc[changed.game_date.ge(day), "minutes"] = 48
    after = feature_table(changed)
    mask = original.game_date.le(day)
    pd.testing.assert_frame_equal(original.loc[mask, MINUTE_FEATURES], after.loc[mask, MINUTE_FEATURES])
