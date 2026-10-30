import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.analysis_archive import archive_snapshot, connect_archive, read_snapshots
from src.forecast_performance import (
    calibration_bins,
    capture_integrity,
    paired_comparison,
    performance_rows,
    probability_metrics,
    quantity_metrics,
)


def example():
    return dict(
        game_key="2026-10-02:BOS:NYK",
        day="2026-10-02",
        state="pre",
        home="BOS",
        away="NYK",
        captured_at="2026-10-02T13:00:00+00:00",
        kickoff="2026-10-02T23:00:00+00:00",
        history_end="2026-10-01",
        model={"id": "fixture", "train_end": "2026-10-01"},
        players=[
            dict(
                player_id=pid,
                name=f"Player {pid}",
                team="BOS",
                minutes=30,
                stats={
                    stat: dict(projected=18, bayes=19, xgboost=21, low=12, high=28, line=19.5, over=0.8)
                    for stat in ("pts", "reb", "ast")
                },
            )
            for pid in (1, 2, 3)
        ],
    )


def test_proof_rejects_late_captures_and_same_day_training():
    snapshot = example()
    assert capture_integrity(snapshot)[0]
    snapshot["captured_at"] = snapshot["kickoff"]
    assert not capture_integrity(snapshot)[0]
    snapshot = example()
    snapshot["model"]["train_end"] = snapshot["day"]
    assert not capture_integrity(snapshot)[0]
    snapshot = example()
    snapshot["captured_at"] = "2026-10-02T13:00:00"
    assert not capture_integrity(snapshot)[0]


def test_results_use_latest_correction_prefer_remote_and_exclude_dnp(tmp_path):
    path = tmp_path / "nba.db"
    local = example()
    archive_snapshot(path, local)
    remote = example()
    remote["captured_at"] = "2026-10-02T14:00:00+00:00"
    archive_snapshot(path, remote, remote=True)
    for snapshot in read_snapshots(path, origin="all"):
        with connect_archive(path) as connection:
            for actual in (20, 22):
                connection.execute(
                    "INSERT INTO snapshot_outcomes VALUES (?,?,?,?,?)",
                    (
                        snapshot["id"],
                        1,
                        "2026-10-03T03:00:00+00:00",
                        str(actual),
                        json.dumps(dict(status="Jogou", actual={s: actual for s in ("pts", "reb", "ast")})),
                    ),
                )
            connection.execute(
                "INSERT INTO snapshot_outcomes VALUES (?,?,?,?,?)",
                (
                    snapshot["id"],
                    2,
                    "2026-10-03T03:00:00+00:00",
                    "dnp",
                    json.dumps(dict(status="Sem participação", actual=None)),
                ),
            )
    table = performance_rows(path, "2026-10-01", "2026-10-03")
    assert len(table) == 9
    selected = table.loc[table.stat.eq("pts")]
    assert quantity_metrics(selected) == dict(n=1, mae=4, bias=-4, coverage=1)
    assert probability_metrics(selected)["brier"] == pytest.approx(0.04)
    assert len(paired_comparison(selected)) == 3
    assert set(paired_comparison(selected).Amostra) == {1}
    assert performance_rows(path, "2026-10-04", "2026-10-05").empty


def test_probability_endpoints_integer_lines_and_empty_samples():
    table = pd.DataFrame(
        dict(
            actual=[0, 20, 10, 12],
            projected=[0, 20, 10, 12],
            line=[0.5, 19.5, 10, 12.5],
            over=[0, 1, 0.9, 0.2],
        )
    )
    report = probability_metrics(table)
    assert report["n"] == 3
    assert report["brier"] == pytest.approx(0.04 / 3)
    assert report["log_loss"] >= 0
    bins = calibration_bins(table)
    assert bins.n.sum() == 3
    assert bins.low.between(0, 1).all() and bins.high.between(0, 1).all()
    assert quantity_metrics(pd.DataFrame())["n"] == 0
    assert paired_comparison(pd.DataFrame()).empty


def test_performance_ui_opens_all_views_with_pending_and_resolved_records(app_db, monkeypatch, tmp_path):
    path = tmp_path / "nba.db"
    archive_snapshot(path, example())
    snapshot = read_snapshots(path)[0]
    with connect_archive(path) as connection:
        connection.execute(
            "INSERT INTO snapshot_outcomes VALUES (?,?,?,?,?)",
            (
                snapshot["id"],
                1,
                "2026-10-03T03:00:00+00:00",
                "actual",
                json.dumps(dict(status="Jogou", actual={s: 20 for s in ("pts", "reb", "ast")})),
            ),
        )
    rows = performance_rows(path, "2026-10-01", "2026-10-03")
    monkeypatch.setattr("src.ui.forecast_performance._load", lambda *args: rows)
    app = AppTest.from_file("../app.py").run(timeout=30)
    app.switch_page("pages/3_Desempenho.py").run(timeout=30)
    assert not app.exception
    for mode in ("Probabilidades", "Minutos", "Comparar modelos"):
        next(item for item in app.segmented_control if item.label == "Analisar").set_value(mode).run(
            timeout=30
        )
        assert not app.exception
