import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.prop_explanations import capture_factors, compare_line


def test_manual_lines_handle_integer_push_and_preserve_the_original():
    estimate = dict(projected=20, dispersion_shape=10, line=19.5, over=0.5, under=0.5)
    original = dict(estimate)
    for line in (19.5, 20, 0):
        result = compare_line(estimate, line)
        assert result is not None
        assert sum(result.values()) == pytest.approx(1)
        assert result["push"] > 0 if int(line) == line else result["push"] == 0
    assert estimate == original
    old = dict(projected=20, line=19.5, over=0.6, under=0.4)
    assert compare_line(old, 19.5)["over"] == 0.6
    assert compare_line(old, 20.5) is None
    with pytest.raises(ValueError):
        compare_line(estimate, float("nan"))


def test_factors_are_observations_and_do_not_serialize_missing_values_as_nan():
    facts = capture_factors(pd.Series(dict(rest=2, is_home=1, pts_mean5=25, pts_mean10=22)))
    assert facts["recent"]["pts"]["last5"] == 25
    assert facts["opponent_allowed"]["pts"] is None
    assert "causal" in facts["note"]
    json.dumps(facts, allow_nan=False)


def _detail(snapshot, player):
    from src.ui.pick_detail import pick_detail

    pick_detail(snapshot, player, key="test_detail")


def test_explanation_ui_compares_a_new_line_and_changes_statistics():
    snapshot = dict(
        home="BOS",
        away="NYK",
        captured_at="2026-10-29T15:00:00+00:00",
        history_end="2026-10-28",
        model={"id": "fixture"},
        source="fixture",
    )
    player = dict(
        name="Test Player",
        minutes=30,
        stats={
            stat: dict(projected=20, dispersion_shape=10, low=10, high=30, line=19.5)
            for stat in ("pts", "reb", "ast")
        },
    )
    app = AppTest.from_function(_detail, args=(snapshot, player)).run(timeout=15)
    assert not app.exception
    app.number_input[0].set_value(20).run(timeout=15)
    assert not app.exception
    assert any(m.label == "Empate na linha" and m.value != "0.0%" for m in app.metric)
    app.segmented_control[0].set_value("reb").run(timeout=15)
    assert not app.exception
