from datetime import date, datetime, timezone

import pandas as pd

from src.nba_schedule import get_next_game_for_team, parse_nba_schedule_payload


def _team(code, city, name):
    return {"teamTricode": code, "teamCity": city, "teamName": name}


def test_parse_official_schedule_payload_normalizes_teams_and_dates():
    payload = {
        "leagueSchedule": {
            "gameDates": [
                {
                    "gameDate": "2026-10-22",
                    "games": [
                        {
                            "gameId": "0022600001",
                            "gameStatus": 1,
                            "gameStatusText": "Scheduled",
                            "gameDateTimeUTC": "2026-10-22T23:30:00Z",
                            "homeTeam": _team("NYK", "New York", "Knicks"),
                            "awayTeam": _team("PHI", "Philadelphia", "76ers"),
                            "arenaName": "Madison Square Garden",
                        }
                    ],
                }
            ]
        }
    }
    result = parse_nba_schedule_payload(payload)
    assert len(result) == 1
    assert result.iloc[0]["game_date"].date() == date(2026, 10, 22)
    assert result.iloc[0]["home_team_tricode"] == "NYK"
    assert result.iloc[0]["home_team_name"] == "New York Knicks"
    assert result.iloc[0]["away_team_name"] == "Philadelphia 76ers"


def test_get_next_game_chooses_first_future_scheduled_game_for_team():
    schedule = pd.DataFrame(
        [
            {
                "game_id": "done",
                "game_date": pd.Timestamp("2026-10-20"),
                "game_datetime_utc": pd.Timestamp("2026-10-20T23:00:00Z"),
                "game_status": 3,
                "home_team_tricode": "NYK",
                "home_team_name": "New York Knicks",
                "away_team_tricode": "BOS",
                "away_team_name": "Boston Celtics",
            },
            {
                "game_id": "later",
                "game_date": pd.Timestamp("2026-10-24"),
                "game_datetime_utc": pd.Timestamp("2026-10-25T00:00:00Z"),
                "game_status": 1,
                "home_team_tricode": "PHI",
                "home_team_name": "Philadelphia 76ers",
                "away_team_tricode": "NYK",
                "away_team_name": "New York Knicks",
            },
            {
                "game_id": "next",
                "game_date": pd.Timestamp("2026-10-22"),
                "game_datetime_utc": pd.Timestamp("2026-10-22T23:30:00Z"),
                "game_status": 1,
                "home_team_tricode": "NYK",
                "home_team_name": "New York Knicks",
                "away_team_tricode": "PHI",
                "away_team_name": "Philadelphia 76ers",
            },
        ]
    )
    result = get_next_game_for_team(
        schedule, "nyk", now=datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    )
    assert result is not None
    assert result["game_id"] == "next"
    assert result["is_home_for_team"] is True
    assert result["opponent_tricode"] == "PHI"
    assert result["opponent_name"] == "Philadelphia 76ers"


def test_get_next_game_skips_same_day_games_that_already_started():
    schedule = pd.DataFrame(
        [
            {
                "game_id": "started",
                "game_date": pd.Timestamp("2026-10-21"),
                "game_datetime_utc": pd.Timestamp("2026-10-21T13:00:00Z"),
                "game_status": 1,
                "home_team_tricode": "NYK",
                "home_team_name": "New York Knicks",
                "away_team_tricode": "BOS",
                "away_team_name": "Boston Celtics",
            },
            {
                "game_id": "tomorrow",
                "game_date": pd.Timestamp("2026-10-22"),
                "game_datetime_utc": pd.Timestamp("2026-10-22T23:00:00Z"),
                "game_status": 1,
                "home_team_tricode": "BOS",
                "home_team_name": "Boston Celtics",
                "away_team_tricode": "NYK",
                "away_team_name": "New York Knicks",
            },
        ]
    )
    result = get_next_game_for_team(
        schedule, "NYK", now=datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc)
    )
    assert result is not None
    assert result["game_id"] == "tomorrow"
    assert result["is_home_for_team"] is False


def test_get_next_game_returns_none_when_team_has_no_future_game():
    schedule = pd.DataFrame(
        [
            {
                "game_id": "final",
                "game_date": pd.Timestamp("2026-10-20"),
                "game_datetime_utc": pd.Timestamp("2026-10-20T23:00:00Z"),
                "game_status": 3,
                "home_team_tricode": "NYK",
                "home_team_name": "New York Knicks",
                "away_team_tricode": "BOS",
                "away_team_name": "Boston Celtics",
            }
        ]
    )
    assert get_next_game_for_team(schedule, "NYK", now=date(2026, 10, 21)) is None
