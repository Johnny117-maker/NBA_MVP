from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from src.injuries import injury_snapshot, refresh_injuries
from src.live_providers import ProviderError
from src.live_store import set_state
from src.live_types import LiveGame
from src.player_matchups import collect_pending_matchups
from src.season_sync import SeasonSync


@pytest.mark.parametrize("recovered_provider", ["NBA", "ESPN"])
def test_new_monitor_retries_public_provider_after_temporary_network_failure(
    tmp_path, monkeypatch, recovered_provider
):
    path = tmp_path / "nba.db"
    now = datetime(2026, 10, 28, 17, tzinfo=UTC)
    connected = False
    calls = []
    set_state(path, "archive_next", now.timestamp() + 3600)
    monkeypatch.setattr("src.season_sync.utc_now", lambda: now)
    monkeypatch.setattr("src.analysis_archive.run_daily_analysis", lambda _: {})

    def fetch(client, day, provider):
        calls.append(provider)
        if not connected or provider != recovered_provider:
            raise ProviderError("Conexão recusada nesta rede")
        return [
            LiveGame(
                "public-test", provider, day.isoformat(), "2026-27", "BOS", "NYK", "pre", now.isoformat()
            )
        ]

    monkeypatch.setattr("src.season_sync.fetch_public_live", fetch)
    failed = SeasonSync(path).run_once(date(2026, 10, 28))
    assert not failed["live_available"]
    assert calls == ["NBA", "ESPN"]
    calls.clear()
    connected = True
    now += timedelta(seconds=301)
    recovered = SeasonSync(path).run_once(date(2026, 10, 28))
    assert recovered["live_available"]
    assert recovered["live_source"] == recovered_provider
    assert recovered_provider in calls


def test_direct_injury_feed_replaces_fallback_when_available_again(tmp_path, monkeypatch):
    path = tmp_path / "nba.db"
    now = datetime(2026, 10, 29, 12, tzinfo=UTC)
    set_state(
        path,
        "injury_snapshot",
        {
            "rows": [],
            "source": "SportsDataverse / ESPN",
            "source_updated": "2026-10-28T18:00Z",
            "source_as_of": "2026-10-28",
            "daily_snapshot": True,
        },
    )
    set_state(path, "injury_attempt", {"available": True, "errors": ["ESPN: ProviderError"]})
    monkeypatch.setattr("src.injuries.utc_now", lambda: now)
    calls = []

    class RecoveredClient:
        def get(self, provider, url, **kwargs):
            calls.append((provider, url))
            assert provider == "ESPN" and url.endswith("/nba/injuries")
            return {
                "injuries": [
                    {
                        "displayName": "Boston Celtics",
                        "injuries": [
                            {
                                "athlete": {"id": "100", "displayName": "Atleta de teste"},
                                "status": "Questionable",
                                "details": {},
                            }
                        ],
                    }
                ]
            }

    refresh_injuries(path, client=RecoveredClient())
    rows, state = injury_snapshot(path)
    assert len(calls) == 1
    assert state["source"] == "ESPN"
    assert not state["daily_snapshot"]
    assert not state["stale"]
    assert state["errors"] == []
    assert rows.iloc[0].status == "Questionável"


def test_matchups_retry_same_game_in_next_batch_after_connection_refusal(tmp_path, monkeypatch):
    path = tmp_path / "nba.db"
    now = datetime(2026, 10, 29, tzinfo=UTC)
    monkeypatch.setattr("src.live_types.current_season", lambda: "2026-27")
    monkeypatch.setattr("src.player_matchups.utc_now", lambda: now)
    monkeypatch.setattr(
        "src.player_matchups.read_assets",
        lambda _: pd.DataFrame(
            [
                {"tag": "nba_stats_schedules", "year": 2027, "relative_path": "schedule.parquet"},
            ]
        ),
    )
    monkeypatch.setattr(
        "src.player_matchups.pd.read_parquet",
        lambda _: pd.DataFrame(
            [
                {"game_id": "0022600001", "game_date": "2026-10-28", "home_wl": "W"},
            ]
        ),
    )
    connected = False
    calls = []

    def collect(db_path, game_id):
        calls.append(game_id)
        if not connected:
            raise ConnectionError("Conexão recusada nesta rede")
        return 3

    monkeypatch.setattr("src.player_matchups.collect_game_matchups", collect)
    assert collect_pending_matchups(path)["error"] == "ConnectionError"
    connected = True
    result = collect_pending_matchups(path)
    assert result == {"collected": 1, "rows": 3, "error": None}
    assert calls == ["0022600001", "0022600001"]
