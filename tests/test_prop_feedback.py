import copy
import json

import numpy as np
import pandas as pd
import pytest

from src.analysis_archive import archive_snapshot, connect_archive, read_snapshots
from src.prop_feedback import evaluate_feedback, feedback_rows, refresh_prop_feedback
from src.prop_training import FEATURES, STATS, PropsBundle, project_props


def samples(*, changed_test=False):
    rows = []
    for index, day in enumerate(pd.date_range("2026-09-01", periods=12)):
        for player in range(40):
            for stat, low, high in (("pts", 10, 20), ("reb", 4, 8), ("ast", 2, 6)):
                rows.append(
                    dict(
                        day=day.date().isoformat(),
                        game=str(index),
                        player=str(player),
                        team="BOS",
                        stat=stat,
                        bayes=low,
                        ml=high,
                        base=(low + high) / 2,
                        actual=(low + high) / 2 if changed_test and index >= 8 else high,
                    )
                )
    return pd.DataFrame(rows)


def test_feedback_is_adopted_only_after_improvement_on_later_dates():
    report = evaluate_feedback(samples(), "2026-09-13")
    assert report["status"] == "Ajustes validados"
    for stat in STATS:
        result = report["stats"][stat]
        assert result["fit_end"] < result["test_start"] <= result["test_end"] < report["before_day"]
        assert result["status"] == "Aplicado"
        assert result["candidate_mae"] < result["base_mae"]
        assert result["weight"] == 1.0
    rejected = evaluate_feedback(samples(changed_test=True), "2026-09-13")
    assert rejected["status"] == "Modelo base mantido"
    assert all(item["status"] == "Modelo base mantido" for item in rejected["stats"].values())


def test_one_round_and_missing_results_never_activate_adjustments():
    table = samples()
    report = evaluate_feedback(table.loc[table.day.eq("2026-09-01")], "2026-09-13")
    assert report["status"] == "Acumulando resultados"
    assert all(item["status"] == "Aguardando amostra" for item in report["stats"].values())
    assert evaluate_feedback(pd.DataFrame(), "2026-09-13")["status"] == "Aguardando resultados"


def stored_payload(day, *, remote=False):
    return dict(
        game_key=f"{day}:BOS:NYK",
        day=day,
        state="pre",
        home="BOS",
        away="NYK",
        captured_at=day + "T13:00:00+00:00" if not remote else day + "T14:00:00+00:00",
        kickoff=day + "T23:00:00+00:00",
        history_end="2026-09-01",
        model={"train_end": "2026-09-01"},
        players=[
            dict(
                player_id=pid,
                name=f"Player {pid}",
                team="BOS",
                stats={stat: dict(bayes=10, xgboost=20, ml_weight=0.5, projected=15) for stat in STATS},
            )
            for pid in (1, 2)
        ],
    )


def test_only_confirmed_prior_games_are_used_without_duplicates_or_dnp_zeros(tmp_path):
    path = tmp_path / "nba.db"
    for day, remote in (("2026-09-10", False), ("2026-09-10", True), ("2026-09-11", False)):
        archive_snapshot(path, stored_payload(day, remote=remote), remote=remote)
    originals = copy.deepcopy(read_snapshots(path, origin="all"))
    with connect_archive(path) as connection:
        for snapshot in originals:
            for pid in (1, 2):
                outcome = dict(
                    status="Jogou" if pid == 1 else "Sem participação",
                    actual={stat: 20 for stat in STATS} if pid == 1 else None,
                )
                connection.execute(
                    "INSERT INTO snapshot_outcomes VALUES (?,?,?,?,?)",
                    (snapshot["id"], pid, "2026-09-12T03:00:00+00:00", "fixture", json.dumps(outcome)),
                )
    table = feedback_rows(path, "2026-09-11")
    assert len(table) == 3  # Uma previsão por jogo/jogador/estatística, preferindo GitHub.
    assert set(table.actual) == {20}
    assert set(table.day) == {"2026-09-10"}
    assert refresh_prop_feedback(path, "2026-09-11") == refresh_prop_feedback(path, "2026-09-11")
    assert read_snapshots(path, origin="all") == originals


def test_adjustments_affect_only_new_projections_and_recompute_intervals():
    class FixedModel:
        def predict(self, frame):
            return np.full(len(frame), 20.0)

    manifest = dict(weights={s: 0.5 for s in STATS}, dispersion={s: 10.0 for s in STATS})
    bundle = PropsBundle({s: FixedModel() for s in STATS}, copy.deepcopy(manifest))
    row = dict.fromkeys(FEATURES, 0.0)
    row["expected_minutes"] = 30
    for stat in STATS:
        row.update({f"{stat}_bayes": 10, f"{stat}_alpha": 20, f"{stat}_dynamic": 0.5})
    base = project_props(pd.Series(row), bundle)
    bundle.manifest["feedback"] = dict(
        id="feedback-test", stats={s: dict(status="Aplicado", weight=1.0, correction=0.0) for s in STATS}
    )
    adjusted = project_props(pd.Series(row), bundle)
    for stat in STATS:
        assert base["stats"][stat]["projected"] == 15
        estimate = adjusted["stats"][stat]
        assert estimate["projected"] == 20
        assert estimate["base_projected"] == 15
        assert estimate["feedback_id"] == "feedback-test"
        assert estimate["over"] + estimate["under"] == pytest.approx(1)
        assert estimate["low"] <= estimate["projected"] <= estimate["high"]
