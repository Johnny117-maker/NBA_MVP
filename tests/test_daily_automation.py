from datetime import UTC, datetime

import pandas as pd
import pytest

from src.daily_automation import generate_daily_archive
from src.live_types import LiveGame


@pytest.mark.parametrize("case", ["unavailable", "missed_window", "no_injury_bulletin"])
def test_missing_inputs_never_create_retrospective_or_unchecked_predictions(tmp_path, monkeypatch, case):
    moment = datetime(2026, 10, 29, 18, tzinfo=UTC)
    monkeypatch.setattr("src.daily_automation.utc_now", lambda: moment)
    monkeypatch.setattr("src.daily_automation.sync_remote_archive", lambda *a, **k: {})
    monkeypatch.setattr("src.daily_automation.refresh_injuries", lambda *a, **k: None)
    monkeypatch.setattr("src.daily_automation.injury_snapshot", lambda *a: (pd.DataFrame(), {}))
    monkeypatch.setattr(
        "src.daily_automation.SeasonSync.run_once",
        lambda *a: {"live_available": False, "errors": ["Fonte indisponível"]},
    )
    games = (
        []
        if case == "unavailable"
        else [
            LiveGame(
                "fixture",
                "fixture",
                "2026-10-29",
                "2026-27",
                "BOS",
                "NYK",
                "final" if case == "missed_window" else "pre",
                moment.isoformat(),
                kickoff="2026-10-29T17:00:00+00:00"
                if case == "missed_window"
                else "2026-10-29T23:00:00+00:00",
            )
        ]
    )
    monkeypatch.setattr("src.daily_automation.read_live_games", lambda *a: games)

    def forbidden(*args, **kwargs):
        pytest.fail("Dados insuficientes não devem iniciar treino nem produzir palpites.")

    monkeypatch.setattr("src.daily_automation.load_research_history", forbidden)
    monkeypatch.setattr("src.daily_automation.create_daily_snapshots", forbidden)
    published = []
    monkeypatch.setattr(
        "src.daily_automation.publish_day",
        lambda client, day, snapshots, report: published.append((snapshots, dict(report))),
    )
    report = generate_daily_archive(tmp_path / "nba.db", object(), tmp_path / "report")
    assert report["games_saved"] == report["players_saved"] == 0
    assert published[0][0] == []
    if case == "unavailable":
        assert report["status"] == "source_unavailable"
    elif case == "missed_window":
        assert report["missing"][0]["reason"] == "Janela pré-jogo perdida"
    else:
        assert "boletim" in report["errors"][-1]
    assert (tmp_path / "report/report.json").is_file()
