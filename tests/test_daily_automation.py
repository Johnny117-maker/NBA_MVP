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


def _scenario(tmp_path, monkeypatch, moment, kickoff):
    monkeypatch.setattr("src.daily_automation.utc_now", lambda: moment)
    monkeypatch.setattr("src.daily_automation.sync_remote_archive", lambda *a, **k: {})
    monkeypatch.setattr("src.daily_automation.refresh_injuries", lambda *a, **k: None)
    monkeypatch.setattr("src.daily_automation.injury_snapshot", lambda *a: (pd.DataFrame(), {}))
    monkeypatch.setattr(
        "src.daily_automation.SeasonSync.run_once", lambda *a: {"live_available": True, "errors": []}
    )
    game = LiveGame(
        "fixture", "fixture", "2026-11-06", "2026-27", "CLE", "PHI", "pre", moment.isoformat(),
        kickoff=kickoff,
    )
    monkeypatch.setattr("src.daily_automation.read_live_games", lambda *a: [game])
    published = []
    monkeypatch.setattr(
        "src.daily_automation.publish_day",
        lambda client, day, snapshots, report: published.append(dict(report)),
    )
    return game, published


def test_games_far_from_tipoff_wait_for_the_capture_window(tmp_path, monkeypatch):
    # 03:54 em Brasília: o histórico ainda não tem os jogos da noite anterior.
    moment = datetime(2026, 11, 6, 6, 54, tzinfo=UTC)
    _, published = _scenario(tmp_path, monkeypatch, moment, "2026-11-07T00:30:00+00:00")

    def forbidden(*args, **kwargs):
        pytest.fail("Fora da janela de captura não se gera palpite.")

    monkeypatch.setattr("src.daily_automation.load_research_history", forbidden)
    monkeypatch.setattr("src.daily_automation.create_daily_snapshots", forbidden)
    report = generate_daily_archive(tmp_path / "nba.db", object(), tmp_path / "report")

    assert report["games_saved"] == 0
    assert report["missing"] == []
    assert report["status"] == "complete"
    assert report["waiting"][0]["game_key"] == "2026-11-06:CLE:PHI"
    assert report["waiting"][0]["capture_from"] == "2026-11-06T18:30:00+00:00"
    assert published[0]["waiting"]


def test_game_inside_the_window_is_captured_with_the_latest_history(tmp_path, monkeypatch):
    moment = datetime(2026, 11, 6, 20, 17, tzinfo=UTC)  # 4h13 antes do jogo
    _, _ = _scenario(tmp_path, monkeypatch, moment, "2026-11-07T00:30:00+00:00")
    monkeypatch.setattr(
        "src.daily_automation.injury_snapshot", lambda *a: (pd.DataFrame(), {"source": "teste"})
    )
    monkeypatch.setattr("src.daily_automation.bulletin_usable", lambda *a: True)
    monkeypatch.setattr("src.daily_automation.refresh_prop_feedback", lambda *a: {})
    captured = []
    monkeypatch.setattr("src.daily_automation.load_research_history", lambda *a: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr("src.daily_automation.ensure_props_bundle", lambda *a: None)
    monkeypatch.setattr("src.daily_automation.daily_team_picks", lambda *a: {})
    monkeypatch.setattr(
        "src.daily_automation.create_daily_snapshots",
        lambda db, games, *a, **k: captured.extend(game.key for game in games) or len(games),
    )
    report = generate_daily_archive(tmp_path / "nba.db", object(), tmp_path / "report")

    assert captured == ["2026-11-06:CLE:PHI"]
    assert report["waiting"] == []
    assert report["generated"] == 1
