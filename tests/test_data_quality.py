from datetime import UTC, datetime, timedelta

import pandas as pd

from src.data_quality import bulletin_quality, bulletin_usable, collection_quality
from src.injuries import current_pick_players, filter_candidate_rows
from src.live_store import set_state

NOW = datetime(2026, 10, 29, 18, tzinfo=UTC)


def test_old_reference_cannot_be_disguised_by_a_recent_download():
    state = dict(source="fixture", source_updated=NOW.isoformat(), source_as_of="2026-10-20")
    assert not bulletin_usable(state, NOW)
    state["source_as_of"] = "2026-10-29"
    assert bulletin_quality(state, NOW)["level"] == "current"
    state["source_updated"] = (NOW - timedelta(hours=49)).isoformat()
    assert not bulletin_usable(state, NOW)
    assert not bulletin_usable({}, NOW)


def test_stale_bulletin_pauses_individual_picks_without_deleting_the_saved_state(tmp_path, monkeypatch):
    path = tmp_path / "nba.db"
    monkeypatch.setattr("src.injuries.utc_now", lambda: NOW)
    monkeypatch.setattr("src.data_quality.utc_now", lambda: NOW)
    state = dict(
        source="fixture",
        source_updated=(NOW - timedelta(hours=49)).isoformat(),
        source_as_of="2026-10-20",
        rows=[],
    )
    set_state(path, "injury_snapshot", state)
    pool = pd.DataFrame([dict(player_name="Player One")])
    assert current_pick_players(path, pool).empty
    candidates = [
        dict(state="pre", player_name="Player One", player_id=1, game_key="game"),
        dict(state="live", player_name="Player One", player_id=1, game_key="game-live"),
    ]
    assert filter_candidate_rows(path, candidates) == [candidates[1]]
    state.update(source_updated=NOW.isoformat(), source_as_of="2026-10-29")
    set_state(path, "injury_snapshot", state)
    assert len(current_pick_players(path, pool)) == 1


def test_collection_freshness_is_not_presented_as_prediction_accuracy():
    recent = dict(live_available=True, live_success_at=NOW.isoformat())
    assert collection_quality(recent, NOW)["level"] == "current"
    recent["live_available"] = False
    assert collection_quality(recent, NOW)["label"] == "Dados periódicos"
    recent["live_success_at"] = (NOW - timedelta(hours=7)).isoformat()
    assert collection_quality(recent, NOW)["label"] == "Dados defasados"
