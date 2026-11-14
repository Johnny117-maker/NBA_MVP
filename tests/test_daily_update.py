import sqlite3
from datetime import UTC, datetime, time, timedelta

import pytest

from src import daily_update
from src.daily_update import day_coverage, last_game_day, run_daily_update
from src.live_store import get_state, save_live_games
from src.live_types import LiveGame
from src.store import init_db

# Relativo a hoje: a base descarta jogos com mais de 7 dias.
DAY = (datetime.now(UTC) - timedelta(days=1)).date()
DAY_TEXT = DAY.isoformat()


def _game(home, away, state="final", day=DAY_TEXT, regular=True):
    fetched = datetime.now(UTC).isoformat()
    game = LiveGame(f"id-{home}", "fixture", day, "2026-27", home, away, state, fetched)
    game.regular_season = regular
    return game


def _save_final_in_history(path, count, day=DAY_TEXT):
    with sqlite3.connect(path) as connection:
        for number in range(count):
            connection.execute(
                "INSERT INTO games (game_id, game_date, season, home_team, away_team, "
                "home_points, away_points) VALUES (?, ?, '2026-27', ?, ?, 100, 90)",
                (f"g{day}{number}", day, f"H{number}", f"A{number}"),
            )


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "nba.db"
    init_db(path)
    return path


def test_coverage_is_complete_when_every_final_game_is_in_the_history(db):
    save_live_games(db, [_game("CLE", "PHI"), _game("BOS", "NYK")])
    _save_final_in_history(db, 2)
    result = day_coverage(db, DAY)
    assert result["status"] == "complete"
    assert (result["scheduled"], result["finals"], result["saved"], result["missing"]) == (2, 2, 2, 0)


def test_coverage_flags_a_final_game_missing_from_the_history(db):
    save_live_games(db, [_game("CLE", "PHI"), _game("BOS", "NYK")])
    _save_final_in_history(db, 1)
    result = day_coverage(db, DAY)
    assert result["status"] == "incomplete"
    assert result["missing"] == 1


def test_coverage_flags_games_that_are_not_final_yet(db):
    save_live_games(db, [_game("CLE", "PHI"), _game("BOS", "NYK", state="live")])
    _save_final_in_history(db, 1)
    result = day_coverage(db, DAY)
    assert result["status"] == "incomplete"
    assert result["pending"] == 1


def test_coverage_ignores_postponed_and_non_regular_season_games(db):
    save_live_games(
        db,
        [_game("CLE", "PHI"), _game("BOS", "NYK", state="unavailable"), _game("LAL", "DEN", regular=False)],
    )
    _save_final_in_history(db, 1)
    assert day_coverage(db, DAY)["status"] == "complete"


def test_coverage_without_games_is_not_an_error(db):
    assert day_coverage(db, DAY)["status"] == "no_games"
    assert last_game_day(db) is None


class _FakeSync:
    """Substitui a sincronização real: o dia anterior só fica completo na tentativa indicada."""

    def __init__(self, db, complete_on, calls):
        self.db, self.complete_on, self.calls = db, complete_on, calls

    def request_refresh(self):
        self.calls.append("refresh")

    def run_once(self, day):
        self.calls.append("sync")
        if self.calls.count("sync") >= self.complete_on:
            _save_final_in_history(self.db, 1)
        return {
            "archive_success_at": datetime.now(UTC).isoformat(),
            "changed_games": 1,
            "errors": [],
        }


_NOW = datetime.combine(DAY + timedelta(days=1), time(10), tzinfo=UTC)


def _patch_sync(monkeypatch, db, complete_on, calls):
    monkeypatch.setattr(daily_update, "SeasonSync", lambda *a, **k: _FakeSync(db, complete_on, calls))
    monkeypatch.setattr(daily_update, "utc_now", lambda: _NOW)


def test_update_retries_until_the_previous_day_is_published(db, monkeypatch):
    save_live_games(db, [_game("CLE", "PHI")])
    calls, waits = [], []
    _patch_sync(monkeypatch, db, complete_on=2, calls=calls)
    report = run_daily_update(db, attempts=3, wait_seconds=60, sleep=waits.append)

    assert report["status"] == "ok"
    assert len(report["attempts"]) == 2
    assert waits == [60]
    assert calls == ["refresh", "sync", "refresh", "sync"]
    assert report["previous_day"]["status"] == "complete"
    assert get_state(db, "daily_update")["status"] == "ok"


def test_update_reports_incomplete_when_the_source_never_publishes(db, monkeypatch):
    save_live_games(db, [_game("CLE", "PHI")])
    calls = []
    _patch_sync(monkeypatch, db, complete_on=99, calls=calls)
    report = run_daily_update(db, attempts=2, wait_seconds=0, sleep=lambda seconds: None)
    assert report["status"] == "incomplete"
    assert len(report["attempts"]) == 2
    assert report["previous_day"]["missing"] == 1


def test_update_reports_source_unavailable_when_nothing_answers(db, monkeypatch):
    class Offline(_FakeSync):
        def run_once(self, day):
            return {"errors": ["fonte indisponível"], "changed_games": 0}

    monkeypatch.setattr(daily_update, "SeasonSync", lambda *a, **k: Offline(db, 1, []))
    monkeypatch.setattr(daily_update, "utc_now", lambda: _NOW)
    report = run_daily_update(db, attempts=1)
    assert report["status"] == "source_unavailable"


def test_update_is_ok_when_there_were_no_games_the_day_before(db, monkeypatch):
    _patch_sync(monkeypatch, db, complete_on=99, calls=[])
    report = run_daily_update(db, attempts=1)
    assert report["status"] == "ok"
    assert report["previous_day"]["status"] == "no_games"
