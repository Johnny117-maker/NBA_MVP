import copy
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.live_types import LiveGame, LivePlayer
from src.prop_model import conditional_prop, opportunity_candidates, player_prior


@pytest.fixture
def context():
    now = datetime(2026, 10, 28, 22, tzinfo=UTC)
    game = LiveGame(
        "0022600050",
        "NBA",
        "2026-10-28",
        "2026-27",
        "BOS",
        "NYK",
        "live",
        now.isoformat(),
        70,
        68,
        3,
        6,
        boxscore_at=now.isoformat(),
    )
    player = LivePlayer("1", "Test Player", "BOS", 22, {"pts": 15, "reb": 5, "ast": 3}, canonical_id=1)
    game.players = [player]
    history = pd.DataFrame(
        {
            "player_id": [1] * 6,
            "player_name": [player.name] * 6,
            "team": ["BOS"] * 6,
            "game_date": pd.date_range("2026-10-16", periods=6, freq="2D"),
            "season": ["2026-27"] * 6,
            "minutes": [30, 32, 34, 30, 32, 34],
            "pts": [20, 25, 22, 24, 20, 26],
            "reb": [5, 6, 7, 6, 5, 7],
            "ast": [3, 4, 5, 4, 3, 5],
        }
    )
    return now, game, player, history


@pytest.mark.parametrize("line", [15, 15.5, 23, 23.5, 30.5])
def test_over_under_and_push_form_a_valid_discrete_distribution(context, line):
    now, game, player, history = context
    row = conditional_prop(history, player, game, "pts", line, now)
    assert row is not None
    assert row["over"] + row["under"] + row["push"] == pytest.approx(1)
    assert all(0 <= row[key] <= 1 for key in ("over", "under", "push"))
    if line != int(line):
        assert row["push"] == pytest.approx(0)
    assert row["low"] >= player.stats["pts"]


def test_already_hit_line_is_not_a_new_opportunity(context):
    now, game, player, history = context
    row = conditional_prop(history, player, game, "pts", 14.5, now)
    assert row["over"] == 1
    assert not row["eligible"]


def test_more_production_raises_over_chance_and_less_clock_time_reduces_it(context):
    now, game, player, history = context
    initial = conditional_prop(history, player, game, "pts", 25.5, now)
    improved = copy.deepcopy(player)
    improved.stats["pts"] = 20
    assert conditional_prop(history, improved, game, "pts", 25.5, now)["over"] > initial["over"]
    later = copy.deepcopy(game)
    later.period, later.clock_minutes = 4, 6
    assert conditional_prop(history, player, later, "pts", 25.5, now)["over"] < initial["over"]


@pytest.mark.parametrize("invalid", ["old", "archive", "missing_minutes", "missing_clock", "missing_stat"])
def test_live_model_refuses_stale_or_incomplete_observations(context, invalid):
    now, game, player, history = context
    if invalid == "old":
        game.boxscore_at = (now - timedelta(minutes=5)).isoformat()
    elif invalid == "archive":
        game.archive = True
    elif invalid == "missing_minutes":
        player.minutes = None
    elif invalid == "missing_clock":
        game.clock_minutes = None
    else:
        player.stats["pts"] = None
    assert conditional_prop(history, player, game, "pts", 20.5, now) is None


def test_current_game_and_future_results_never_change_pregame_prior(context):
    now, game, player, history = context
    original = player_prior(history, 1, game, "pts")
    future = history.tail(1).assign(game_date=pd.Timestamp("2026-10-28"), pts=999)
    changed = pd.concat([history, future], ignore_index=True)
    assert player_prior(changed, 1, game, "pts") == original
    old = history.assign(season="2025-26", game_date=history["game_date"] - pd.Timedelta(days=200))
    assert player_prior(old, 1, game, "pts") is None


def test_finished_games_and_pregames_already_started_do_not_generate_opportunities(context):
    now, game, player, history = context
    game.state = "final"
    assert opportunity_candidates(history, [game], now) == []
    game.state = "pre"
    game.kickoff = (now - timedelta(hours=1)).isoformat()
    assert opportunity_candidates(history, [game], now) == []
