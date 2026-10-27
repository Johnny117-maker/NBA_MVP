import pandas as pd

from src.schedule_storage import read_schedule_cache, save_schedule_cache


def _schedule(game_id="0022600001", day="2026-10-27"):
    return pd.DataFrame([{
        "game_id": game_id,
        "game_date": pd.Timestamp(day),
        "game_datetime_utc": pd.Timestamp(f"{day}T23:30:00Z"),
        "home_team_tricode": "BOS",
        "away_team_tricode": "NYK",
        "home_team_name": "Boston Celtics",
        "away_team_name": "New York Knicks",
        "schedule_source": "NBA oficial",
        "game_status": 1,
    }])


def test_calendar_cache_preserves_ids_dates_and_times(tmp_path):
    path = tmp_path / "calendar.json"
    save_schedule_cache(_schedule(), path)
    result = read_schedule_cache(path)
    assert result.iloc[0]["game_id"] == "0022600001"
    assert result.iloc[0]["game_date"] == pd.Timestamp("2026-10-27")
    assert result.iloc[0]["game_datetime_utc"] == pd.Timestamp("2026-10-27T23:30:00Z")


def test_calendar_cache_merges_dates_and_updates_rescheduled_games(tmp_path):
    path = tmp_path / "calendar.json"
    save_schedule_cache(_schedule(), path)
    save_schedule_cache(_schedule("0022600002", "2026-10-28"), path)
    save_schedule_cache(_schedule("0022600001", "2026-10-29"), path)
    result = read_schedule_cache(path).set_index("game_id")
    assert len(result) == 2
    assert result.loc["0022600001", "game_date"] == pd.Timestamp("2026-10-29")
    assert result.loc["0022600002", "game_date"] == pd.Timestamp("2026-10-28")


def test_empty_response_does_not_overwrite_saved_calendar(tmp_path):
    path = tmp_path / "calendar.json"
    save_schedule_cache(_schedule(), path)
    original = path.read_bytes()
    save_schedule_cache(pd.DataFrame(), path)
    assert path.read_bytes() == original


def test_same_game_from_different_providers_is_not_duplicated(tmp_path):
    path = tmp_path / "calendar.json"
    save_schedule_cache(_schedule(), path)
    alternative = _schedule("401909877")
    alternative["schedule_source"] = "SportsDataverse / ESPN (arquivo público)"
    save_schedule_cache(alternative, path)
    result = read_schedule_cache(path)
    assert len(result) == 1
    assert result.iloc[0]["game_id"] == "401909877"


def test_missing_or_invalid_calendar_cache_does_not_crash(tmp_path):
    path = tmp_path / "calendar.json"
    assert read_schedule_cache(path).empty
    for content in ('{', '{}', '[{"game_id":"invalid"}]'):
        path.write_text(content, encoding="utf-8")
        assert read_schedule_cache(path).empty
