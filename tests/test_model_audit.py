import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts.audit_models import coverage_and_logs


def test_audit_coverage_excludes_future_rows():
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE games (game_date TEXT)")
        connection.executemany("INSERT INTO games VALUES (?)", [("2026-01-01",), ("2026-10-27",)])
        report = coverage_and_logs(connection, "2026-10-27")
    assert report["coverage"]["games"] == {
        "rows": 1,
        "first_game": "2026-01-01",
        "last_game": "2026-01-01",
    }


def test_audit_cli_writes_report_without_modifying_database(app_db, tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_models.py"
    before = hashlib.sha256(app_db.read_bytes()).hexdigest()
    modified_at = app_db.stat().st_mtime_ns
    report_path = tmp_path / "audit.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(app_db),
            "--as-of",
            "2026-10-27",
            "--output",
            str(report_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["coverage"]["games"]["rows"] == 60
    assert report["last_recorded_training"]["player"]["metrics"]["pts_mae"] == 4.1
    assert not report["historical_player_report"]["available"]
    assert app_db.stat().st_mtime_ns == modified_at
    assert hashlib.sha256(app_db.read_bytes()).hexdigest() == before
