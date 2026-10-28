import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from src.app_paths import data_path, report_path, secrets_path
from src.desktop_runtime import _local_request, stop_backend
from src.desktop_seed import build_seed
from src.desktop_support import (
    available_port,
    initialize_user_data,
    instance_hash,
    resource_root,
    server_command,
)
from src.live_store import cache_put, connect_state, state_path


def test_desktop_state_is_independent_of_cwd_and_installation(monkeypatch, tmp_path):
    home = tmp_path / "User with spaces" / "NBA"
    monkeypatch.setenv("NBA_DATA_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    assert data_path("nba.db") == home / "data" / "nba.db"
    assert secrets_path() == home / ".streamlit" / "secrets.toml"
    (home / "reports").mkdir(parents=True)
    report = home / "reports" / "test.csv"
    report.write_text("my report", encoding="utf-8")
    assert report_path("test.csv") == report


def test_seed_initialization_never_replaces_existing_user_data_or_ships_secrets(tmp_path):
    resources = tmp_path / "read-only-resources"
    (resources / "seed").mkdir(parents=True)
    (resources / "seed" / "nba.db").write_bytes(b"public-data-v1")
    (resources / ".streamlit").mkdir()
    (resources / ".streamlit" / "config.toml").write_text('[theme]\nbase="dark"', encoding="utf-8")
    (resources / ".streamlit" / "secrets.toml").write_text("PRIVATE-KEY", encoding="utf-8")
    home = tmp_path / "profile"
    initialize_user_data(home, resources)
    assert (home / "data" / "nba.db").read_bytes() == b"public-data-v1"
    assert not (home / ".streamlit" / "secrets.toml").exists()
    (home / "data" / "nba.db").write_bytes(b"user-history")
    (resources / "seed" / "nba.db").write_bytes(b"public-data-v2")
    initialize_user_data(home, resources)
    assert (home / "data" / "nba.db").read_bytes() == b"user-history"
    assert (home / ".streamlit" / "config.toml").exists()


def test_compact_seed_only_contains_public_data_and_complete_player_dates(app_db, tmp_path):
    source = tmp_path / "source.db"
    with sqlite3.connect(app_db) as original, sqlite3.connect(source) as clone:
        original.backup(clone)
        clone.execute(
            "INSERT INTO team_predictions (created_at,home_team,away_team,home_win_probability,"
            "predicted_home_score,predicted_away_score,confidence) VALUES (?,?,?,?,?,?,?)",
            ("2026-10-28", "PRIVATE-PREDICTION", "OTHER", 0.7, 100, 90, "private"),
        )
    cache_put(source, "private-api-cache", "DO-NOT-DISTRIBUTE")
    target = tmp_path / "seed" / "nba.db"
    counts = build_seed(source, target, player_limit=1000, shot_limit=20)
    assert 0 < counts["player_game_stats"] <= 1000
    assert counts["player_shots"] == 20
    with sqlite3.connect(source) as original, sqlite3.connect(target) as result:
        assert result.execute("SELECT COUNT(*) FROM team_predictions").fetchone()[0] == 0
        assert result.execute("SELECT COUNT(*) FROM player_predictions").fetchone()[0] == 0
        for day, count in result.execute("SELECT date(game_date),COUNT(*) FROM player_game_stats GROUP BY 1"):
            assert (
                original.execute(
                    "SELECT COUNT(*) FROM player_game_stats WHERE minutes>0 AND date(game_date)=?", (day,)
                ).fetchone()[0]
                == count
            )
    if state_path(target).exists():
        with connect_state(target) as state:
            assert state.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0] == 0
    with pytest.raises(FileExistsError):
        build_seed(source, target)


def test_frozen_child_reuses_its_exe_without_external_python(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/App/NBAAnalyticsLab.exe")
    command = server_command(12345, tmp_path, 321)
    assert command[0] == "C:/App/NBAAnalyticsLab.exe"
    assert "desktop_launcher.py" not in " ".join(command)
    assert "--serve" in command
    assert "321" in command


def test_local_backend_serves_ui_authenticates_shutdown_and_stops(tmp_path):
    home = tmp_path / "desktop-profile"
    port = available_port()
    token = "desktop-test-token"
    url = f"http://127.0.0.1:{port}"
    log = tmp_path / "server.log"
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import streamlit,sys,runpy,pathlib; "
                "streamlit.config.set_option('global.developmentMode',True); "
                "sys.argv=sys.argv[1:]; sys.path.insert(0,str(pathlib.Path(sys.argv[0]).parent)); "
                "runpy.run_path(sys.argv[0],run_name='__main__')",
                str(resource_root() / "desktop_launcher.py"),
                "--serve",
                "--port",
                str(port),
                "--data-dir",
                str(home),
                "--no-sync",
            ],
            env=dict(os.environ, NBA_DESKTOP_TOKEN=token),
            cwd=tmp_path,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail(log.read_text(encoding="utf-8"))
                try:
                    health = _local_request(url + "/desktop/health")
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("Servidor local não ficou pronto: " + log.read_text(encoding="utf-8"))
            assert health["instance"] == instance_hash(token)
            assert token not in json.dumps(health)
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=3) as page:
                assert "streamlit" in page.read().decode().lower()
            with pytest.raises(urllib.error.HTTPError) as denied:
                _local_request(url + "/desktop/shutdown", token="wrong")
            assert denied.value.code == 403
            assert process.poll() is None
            stop_backend(process, url, token)
            assert process.returncode == 0
            assert (home / "data" / "nba.db").exists()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
