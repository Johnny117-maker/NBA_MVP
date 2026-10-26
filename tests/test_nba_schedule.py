from datetime import UTC, date, datetime

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
        schedule, "nyk", now=datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
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
        schedule, "NYK", now=datetime(2026, 10, 21, 16, 0, tzinfo=UTC)
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


def test_parse_espn_scoreboard_payload_normalizes_names_dates_and_source():
    from src.nba_schedule import parse_espn_scoreboard_payload

    payload = {
        "events": [
            {
                "id": "401999001",
                "date": "2026-10-22T23:30:00Z",
                "name": "Toronto Raptors at Boston Celtics",
                "competitions": [
                    {
                        "id": "401999001",
                        "date": "2026-10-22T23:30:00Z",
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {
                                    "abbreviation": "BOS",
                                    "displayName": "Boston Celtics",
                                },
                            },
                            {
                                "homeAway": "away",
                                "team": {
                                    "abbreviation": "TOR",
                                    "displayName": "Toronto Raptors",
                                },
                            },
                        ],
                        "status": {"type": {"state": "pre", "detail": "Scheduled"}},
                        "venue": {"fullName": "TD Garden"},
                    }
                ],
            }
        ]
    }
    result = parse_espn_scoreboard_payload(payload)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["game_date"].date() == date(2026, 10, 22)
    assert row["home_team_tricode"] == "BOS"
    assert row["away_team_tricode"] == "TOR"
    assert row["game_status"] == 1
    assert row["schedule_source"] == "ESPN (alternativo)"


def test_fetch_nba_schedule_falls_back_to_espn_when_nba_cdn_fails(monkeypatch):
    import requests

    import src.nba_schedule as schedule_module

    payload = {
        "events": [
            {
                "id": "401999002",
                "date": "2026-10-22T23:30:00Z",
                "name": "Toronto Raptors at Boston Celtics",
                "competitions": [
                    {
                        "date": "2026-10-22T23:30:00Z",
                        "competitors": [
                            {
                                "homeAway": "home",
                                "team": {"abbreviation": "BOS", "displayName": "Boston Celtics"},
                            },
                            {
                                "homeAway": "away",
                                "team": {"abbreviation": "TOR", "displayName": "Toronto Raptors"},
                            },
                        ],
                        "status": {"type": {"state": "pre", "detail": "Scheduled"}},
                    }
                ],
            }
        ]
    }

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        if "cdn.nba.com" in url:
            raise requests.ConnectionError("connection reset")
        return Response(payload)

    monkeypatch.setattr(schedule_module.requests, "get", fake_get)
    result = schedule_module.fetch_nba_schedule(
        timeout=0.1, team_tricode="TOR", lookahead_days=5
    )
    assert not result.empty
    assert result.iloc[0]["schedule_source"] == "ESPN (alternativo)"
    assert result.iloc[0]["away_team_tricode"] == "TOR"
    assert calls["n"] == 3


def test_fetch_nba_schedule_error_is_readable_when_all_sources_fail(monkeypatch):
    import requests

    import src.nba_schedule as schedule_module

    def fake_get(url, **kwargs):
        raise requests.ConnectionError("socket details should not leak into UI")

    monkeypatch.setattr(schedule_module.requests, "get", fake_get)
    try:
        schedule_module.fetch_nba_schedule(
            timeout=0.1, team_tricode="TOR", lookahead_days=2
        )
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("Expected RuntimeError when all schedule sources fail")

    assert "NBA e ESPN" in message
    assert "preencha o adversário e a data manualmente" in message.casefold()
    assert "socket details" not in message
