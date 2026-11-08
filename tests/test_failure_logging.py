"""Caminhos de falha com `except Exception` intencional: o erro é registrado e o fluxo continua."""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import pandas as pd

from src import history_normalize, history_sources, player_matchups, research_feeds
from src.live_types import current_season
from src.logging_setup import LEVEL_ENV, configure_logging


def _logged_with_traceback(caplog, fragment: str) -> bool:
    return any(fragment in record.getMessage() and record.exc_info for record in caplog.records)


def test_rim_daily_failure_is_logged_and_saved_as_unavailable(tmp_path, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise ConnectionError("NBA fora do ar")

    monkeypatch.setattr(research_feeds, "collect_rim_defense", fail)
    db_path = tmp_path / "nba.db"
    day = date(2026, 11, 8)
    with caplog.at_level(logging.WARNING, logger="src.research_feeds"):
        state = research_feeds.collect_rim_daily(db_path, day)
    assert state["status"] == "indisponível" and state["error"] == "ConnectionError"
    assert _logged_with_traceback(caplog, "defesa no garrafão")
    # a tentativa do dia fica salva: uma segunda chamada não consulta a fonte de novo
    assert research_feeds.collect_rim_daily(db_path, day)["status"] == "indisponível"


def test_one_failed_download_is_logged_and_the_others_continue(tmp_path, monkeypatch, caplog):
    assets = [SimpleNamespace(tag="t", name=name) for name in ("a.parquet", "b.parquet", "c.parquet")]

    def download(db_path, asset):
        if asset.name == "b.parquet":
            raise OSError("disco cheio")
        return {"status": "downloaded"}

    monkeypatch.setattr(history_sources, "select_assets", lambda *args, **kwargs: assets)
    monkeypatch.setattr(history_sources, "download_asset", download)
    monkeypatch.setattr(history_normalize, "normalize_history", lambda *args, **kwargs: {"errors": []})
    with caplog.at_level(logging.WARNING, logger="src.history_sources"):
        result = history_sources.collect_history(tmp_path / "nba.db", start_year=2025, releases=[])
    assert result["downloaded"] == 2
    assert result["errors"] == [{"tag": "t", "name": "b.parquet", "error": "OSError"}]
    assert _logged_with_traceback(caplog, "b.parquet")


def test_matchup_collection_stops_on_failure_but_keeps_progress_and_logs(tmp_path, monkeypatch, caplog):
    year = int(current_season()[:4]) + 1
    assets = pd.DataFrame([{"tag": "nba_stats_schedules", "year": year, "relative_path": "x.parquet"}])
    schedule = pd.DataFrame(
        {
            "game_id": ["0022500001", "0022500002", "0022500003"],
            "game_date": ["2020-01-01"] * 3,
            "home_wl": ["W", "L", "W"],
        }
    )

    def collect(db_path, game_id):
        if game_id == "0022500002":
            raise RuntimeError("fonte recusou")
        return 7

    monkeypatch.setattr(player_matchups, "read_assets", lambda db_path: assets)
    monkeypatch.setattr(player_matchups.pd, "read_parquet", lambda path: schedule)
    monkeypatch.setattr(player_matchups, "collect_game_matchups", collect)
    with caplog.at_level(logging.WARNING, logger="src.player_matchups"):
        result = player_matchups.collect_pending_matchups(tmp_path / "nba.db")
    assert result == {"collected": 1, "rows": 7, "error": "RuntimeError"}
    assert _logged_with_traceback(caplog, "0022500002")


def test_configure_logging_is_idempotent_and_reads_the_level(monkeypatch):
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        for handler in list(root.handlers):
            if getattr(handler, "_nba_analytics_lab_handler", False):
                root.removeHandler(handler)
        monkeypatch.setenv(LEVEL_ENV, "debug")
        configure_logging()
        configure_logging()
        ours = [h for h in root.handlers if getattr(h, "_nba_analytics_lab_handler", False)]
        assert len(ours) == 1 and root.level == logging.DEBUG
        monkeypatch.setenv(LEVEL_ENV, "valor-invalido")
        configure_logging()
        assert root.level == logging.INFO
        configure_logging("ERROR")
        assert root.level == logging.ERROR
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
