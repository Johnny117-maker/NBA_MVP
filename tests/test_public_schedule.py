from datetime import date

import pandas as pd
import pytest
import requests

from src.nba_schedule import fetch_nba_schedule, get_next_game_for_team
from src.public_schedule import PUBLIC_SCHEDULE_SOURCE, fetch_public_schedule, parse_public_schedule


def _row(**overrides):
    row = {
        "game_id": "401909877",
        "game_date": "2026-10-27",
        "date": "2026-10-28T00:00Z",
        "home_abbreviation": "NY",
        "away_abbreviation": "SA",
        "status_type_state": "pre",
        "status_type_completed": "false",
        "status_type_name": "STATUS_SCHEDULED",
        "status_type_detail": "Scheduled",
        "time_valid": "true",
        "venue_full_name": "Madison Square Garden",
    }
    row.update(overrides)
    return row


def test_public_calendar_normalizes_teams_local_date_and_utc_time():
    result = parse_public_schedule(pd.DataFrame([_row()]))
    game = result.iloc[0]
    assert game["game_id"] == "401909877"
    assert game["game_date"] == pd.Timestamp("2026-10-27")
    assert game["game_datetime_utc"] == pd.Timestamp("2026-10-28T00:00Z")
    assert game["home_team_tricode"] == "NYK"
    assert game["away_team_tricode"] == "SAS"
    assert game["home_team_name"] == "New York Knicks"
    assert game["schedule_source"] == PUBLIC_SCHEDULE_SOURCE


def test_public_calendar_derives_eastern_date_when_local_date_is_missing():
    result = parse_public_schedule(pd.DataFrame([_row(game_date="")]))
    assert result.iloc[0]["game_date"] == pd.Timestamp("2026-10-27")


@pytest.mark.parametrize(
    "state,completed,expected", [("pre", "false", 1), ("in", "false", 2), ("post", "true", 3)]
)
def test_public_calendar_preserves_game_status(state, completed, expected):
    result = parse_public_schedule(
        pd.DataFrame([_row(status_type_state=state, status_type_completed=completed)])
    )
    assert result.iloc[0]["game_status"] == expected


def test_postponed_game_is_not_selected_as_next_scheduled_game():
    frame = parse_public_schedule(pd.DataFrame([_row(status_type_name="STATUS_POSTPONED")]))
    assert frame.iloc[0]["game_status"] == 4
    assert get_next_game_for_team(frame, "NYK", now=date(2026, 10, 27)) is None


def test_unconfirmed_time_is_not_presented_as_a_known_tipoff():
    frame = parse_public_schedule(pd.DataFrame([_row(time_valid="false")]))
    assert pd.isna(frame.iloc[0]["game_datetime_utc"])
    assert frame.iloc[0]["game_date"] == pd.Timestamp("2026-10-27")


def test_unknown_teams_and_invalid_rows_are_omitted():
    rows = [
        _row(),
        _row(game_id="tbd", home_abbreviation="TBA"),
        _row(game_id="same", away_abbreviation="NY"),
        _row(game_id=""),
    ]
    assert list(parse_public_schedule(pd.DataFrame(rows))["game_id"]) == ["401909877"]
    with pytest.raises(ValueError, match="colunas"):
        parse_public_schedule(pd.DataFrame({"wrong": [1]}))
    with pytest.raises(ValueError, match="reconhecíveis"):
        parse_public_schedule(pd.DataFrame([_row(home_abbreviation="TBA")]))


@pytest.mark.parametrize(
    "selected,season", [(date(2026, 10, 27), 2027), (date(2027, 1, 4), 2027), (date(2026, 4, 5), 2026)]
)
def test_public_files_are_addressed_by_season_ending_year(monkeypatch, selected, season):
    urls = []

    class Response:
        content = pd.DataFrame([_row()]).to_csv(index=False).encode()

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        urls.append(url)
        assert "Authorization" not in kwargs.get("headers", {})
        return Response()

    monkeypatch.setattr("src.public_schedule.requests.get", fake_get)
    fetch_public_schedule(selected, lookahead_days=1)
    assert urls[0].endswith(f"nba_schedule_{season}.csv")


def test_calendar_uses_public_files_when_nba_is_unreachable(monkeypatch):
    calls = []

    class Response:
        content = pd.DataFrame([_row()]).to_csv(index=False).encode()

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls.append(url)
        if "cdn.nba.com" in url:
            raise requests.ConnectionError("connection reset")
        assert "github.com/sportsdataverse" in url
        return Response()

    monkeypatch.setattr("src.nba_schedule.requests.get", fake_get)
    result = fetch_nba_schedule(start_date=date(2026, 10, 27), lookahead_days=1)
    assert result.iloc[0]["schedule_source"] == PUBLIC_SCHEDULE_SOURCE
    assert len(calls) == 3  # dois endereços NBA e um arquivo público, sem esperar o fallback diário.
