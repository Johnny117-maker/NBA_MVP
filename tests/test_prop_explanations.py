import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.prop_explanations import capture_factors, compare_line, line_context


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


def test_player_context_excludes_other_players_and_future_results():
    history = pd.DataFrame(
        [
            dict(player_id=1, game_date="2026-10-29", season="2026-27", pts=10, reb=5, ast=3, minutes=30),
            dict(player_id=1, game_date="2026-10-31", season="2026-27", pts=99, reb=99, ast=99, minutes=48),
            dict(player_id=2, game_date="2026-10-29", season="2026-27", pts=99, reb=99, ast=99, minutes=48),
        ]
    )
    facts = capture_factors(pd.Series(dict(player_id=1, game_date="2026-10-30", season="2026-27")), history)
    assert facts["season"]["games"] == 1 and facts["season"]["means"]["pts"] == 10
    player = {"factors": facts}
    half = line_context(player, "pts", 10.5)
    assert half["over_min"] == 11 and half["under_max"] == 10 and half["recent_under"] == 1
    whole = line_context(player, "pts", 10)
    assert whole["over_min"] == 11 and whole["under_max"] == 9 and whole["recent_push"] == 1
    assert line_context({}, "pts", 20.5)["sample"] == 0


def _detail(snapshot, player):
    from src.ui.pick_detail import pick_detail

    pick_detail(snapshot, player, key="test_detail")


def _switching_detail(snapshot, players):
    import streamlit as st

    from src.ui.pick_detail import pick_detail

    name = st.selectbox("Jogador", list(players))
    pick_detail(snapshot, players[name], key="switch_detail")


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
    other = {
        **player,
        "name": "Other Player",
        "stats": {stat: {**estimate, "line": 29.5} for stat, estimate in player["stats"].items()},
    }
    switched = AppTest.from_function(
        _switching_detail, args=(snapshot, {player["name"]: player, other["name"]: other})
    ).run()
    switched.number_input[0].set_value(20.5).run()
    switched.selectbox[0].select("Other Player").run()
    assert not switched.exception
    assert switched.number_input[0].value == 29.5
