from datetime import date

import pandas as pd
import pytest

from src.daily_games import player_snapshot_context, recent_training_sample
from src.data import generate_demo_games
from src.model import GamePrediction
from src.today_picks import build_matchup_pick, round_highlights, upcoming_games


def test_training_limit_preserves_complete_dates():
    rows = pd.DataFrame({"game_date": pd.to_datetime(["2026-01-01"] * 3 + ["2026-01-02"] * 3)})
    sample = recent_training_sample(rows, max_rows=5)
    assert len(sample) == 3
    assert sample["game_date"].eq(pd.Timestamp("2026-01-02")).all()
    with pytest.raises(ValueError, match="data completa"):
        recent_training_sample(rows, max_rows=2)


def test_snapshot_context_keeps_team_medians_and_full_player_history(app_db):
    from src.player_data import load_player_games
    from src.player_metrics import player_snapshot

    history = load_player_games(source="real", db_path=app_db)
    player_id = history.iloc[0]["player_id"]
    context = player_snapshot_context(history, player_id)
    assert len(context) < len(history)
    expected = pd.Series(player_snapshot(history, player_id))
    actual = pd.Series(player_snapshot(context, player_id))
    pd.testing.assert_series_equal(actual, expected)


def test_only_upcoming_games_on_the_requested_day_are_picked():
    rows = []
    for game_id, day, status, kickoff in (
        ("future", "2026-10-27", 1, "2026-10-27T20:00Z"),
        ("live", "2026-10-27", 2, "2026-10-27T20:00Z"),
        ("final", "2026-10-27", 3, "2026-10-27T20:00Z"),
        ("postponed", "2026-10-27", 4, "2026-10-27T20:00Z"),
        ("stale_status", "2026-10-27", 1, "2026-10-27T17:00Z"),
        ("exact_start", "2026-10-27", 1, "2026-10-27T18:00Z"),
        ("tomorrow", "2026-10-28", 1, "2026-10-28T20:00Z"),
        ("unknown_time", "2026-10-27", 1, None),
    ):
        rows.append(
            {"game_id": game_id, "game_date": day, "game_status": status, "game_datetime_utc": kickoff}
        )
    games = upcoming_games(pd.DataFrame(rows), date(2026, 10, 27), pd.Timestamp("2026-10-27T18:00Z"))
    assert games["game_id"].tolist() == ["future", "unknown_time"]


def test_highlights_are_limited_to_the_slate_and_not_duplicated():
    form = pd.DataFrame(
        [
            {
                "player_id": i,
                "player_name": name,
                "team": team,
                "pts_recent": pts,
                "reb_recent": 5,
                "ast_recent": 3,
                "minutes_recent": 30,
                "last_game_date": "2026-10-26",
            }
            for i, name, team, pts in (
                (1, "Boston Star", "BOS", 30),
                (2, "NY Star", "NYK", 25),
                (3, "Not playing today", "LAL", 50),
            )
        ]
    )
    game = {
        "game_id": "g1",
        "home_team_tricode": "NYK",
        "away_team_tricode": "BOS",
        "home_team_name": "New York Knicks",
        "away_team_name": "Boston Celtics",
        "game_status": 1,
    }
    highlights = round_highlights(form, pd.DataFrame([game, game]), top_n=1)
    assert highlights["player_id"].tolist() == [1, 2]
    assert highlights.iloc[0]["opponent_name"] == "New York Knicks"
    assert not highlights.iloc[0]["is_home"]
    assert round_highlights(form, pd.DataFrame([{**game, "game_status": 4}])).empty


def test_old_history_downgrades_confidence_and_same_day_results_are_excluded(monkeypatch):
    history = generate_demo_games(100)
    today = date(2026, 10, 27)
    game = pd.Series(
        {"home_team_name": history.iloc[-1]["home_team"], "away_team_name": history.iloc[-1]["away_team"]}
    )
    future = history.tail(1).copy()
    future["game_date"] = pd.Timestamp(today)
    future[["home_points", "away_points"]] = 999
    predictions = []

    def predict(*args):
        predictions.append(args)
        return GamePrediction(0.7, 0.3, 110, 100, 95, 125, 85, 115, "Alta", [])

    monkeypatch.setattr("src.today_picks.predict_game", predict)
    pick = build_matchup_pick(None, pd.concat([history, future]), game, today)
    assert pick.favorite == game["home_team_name"]
    assert pick.probability == 0.7
    assert pick.confidence == "Baixa · histórico antigo"
    assert pick.last_game_date.date() < today
    assert predictions[0][1]["points_for"] < 999
