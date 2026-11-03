"""Aprendizado pelos erros pré-jogo, com seleção e avaliação em datas distintas."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .entity_ids import normalized_name
from .live_store import get_state, set_state
from .live_types import EASTERN, utc_now
from .prop_training import STATS, PropsBundle

VERSION = "props-feedback-v2"
MIN_ROWS = 120
MIN_DATES = 8
MAX_CORRECTION = {"pts": 3.0, "reb": 1.5, "ast": 1.5}


def feedback_rows(path: str | Path, before_day: str) -> pd.DataFrame:
    from .analysis_archive import archive_path, connect_archive, read_snapshots

    if not archive_path(path).exists():
        return pd.DataFrame()
    earliest = (pd.Timestamp(before_day) - timedelta(days=90)).date().isoformat()
    snapshots = read_snapshots(path, limit=2000)
    now = pd.Timestamp(utc_now())
    rows = []
    with connect_archive(path) as connection:
        for snapshot in snapshots:
            if not earliest <= snapshot["day"] < before_day:
                continue
            # Não aprende de backtests recriados nem de registros feitos após o início.
            if pd.Timestamp(snapshot["captured_at"]) >= pd.Timestamp(snapshot["kickoff"]):
                continue
            for player in snapshot["players"]:
                result = connection.execute(
                    "SELECT payload,recorded_at FROM snapshot_outcomes "
                    "WHERE snapshot_id=? AND player_id=? ORDER BY rowid DESC LIMIT 1",
                    (snapshot["id"], player["player_id"]),
                ).fetchone()
                if result is None or pd.Timestamp(result[1]) > now:
                    continue
                outcome = json.loads(result[0])
                if (
                    outcome.get("status") != "Jogou"
                    or not outcome.get("actual")
                    or not outcome.get("confirmed_final")
                ):
                    continue
                for stat in STATS:
                    estimate = player["stats"].get(stat, {})
                    bayes = estimate.get("bayes")
                    actual = outcome["actual"].get(stat)
                    if bayes is None or actual is None:
                        continue
                    ml = estimate.get("xgboost")
                    weight = float(estimate.get("ml_weight", 0)) if ml is not None else 0.0
                    base = float(
                        estimate.get("base_projected", (1 - weight) * float(bayes) + weight * float(ml or 0))
                    )
                    rows.append(
                        dict(
                            day=snapshot["day"],
                            game=snapshot["game_key"],
                            player=normalized_name(player["name"]),
                            team=player["team"],
                            stat=stat,
                            bayes=float(bayes),
                            ml=float(ml) if ml is not None else np.nan,
                            base=base,
                            actual=float(actual),
                        )
                    )
    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame(rows).drop_duplicates(["game", "player", "team", "stat"])
    valid = np.isfinite(table[["bayes", "base", "actual"]]).all(axis=1)
    valid &= table[["bayes", "base", "actual"]].ge(0).all(axis=1)
    valid &= table.ml.isna() | (np.isfinite(table.ml) & table.ml.ge(0))
    return table.loc[valid].sort_values(["day", "game", "player", "stat"]).reset_index(drop=True)


def _prediction(rows: pd.DataFrame, weight: float | None, correction: float) -> np.ndarray:
    base = (
        rows.base.to_numpy()
        if weight is None
        else np.where(rows.ml.notna(), (1 - weight) * rows.bayes + weight * rows.ml, rows.bayes)
    )
    return np.clip(base + correction, 0, None)


def evaluate_feedback(table: pd.DataFrame, before_day: str) -> dict:
    # A separação usa datas inteiras para não misturar atletas da mesma rodada.
    report: dict = dict(
        version=VERSION,
        before_day=before_day,
        checked_at=utc_now().isoformat(),
        rows=len(table),
        dates=0 if table.empty else int(table.day.nunique()),
        through_day=None if table.empty else str(table.day.max()),
        stats={},
        status="Aguardando resultados" if table.empty else "Acumulando resultados",
    )
    for stat in STATS:
        rows = table.loc[table.stat.eq(stat)] if not table.empty else table
        dates = sorted(rows.day.unique()) if not rows.empty else []
        result: dict = dict(status="Aguardando amostra", rows=len(rows), dates=len(dates))
        report["stats"][stat] = result
        if len(rows) < MIN_ROWS or len(dates) < MIN_DATES:
            continue
        boundary = str(dates[max(1, int(len(dates) * 0.7))])
        fit, test = rows.loc[rows.day.lt(boundary)], rows.loc[rows.day.ge(boundary)]
        if len(fit) < 80 or len(test) < 40 or test.day.nunique() < 3:
            continue
        candidates = []
        for weight in (None, 0.0, 0.25, 0.5, 0.75, 1.0):
            residual = fit.actual.to_numpy() - _prediction(fit, weight, 0)
            correction = float(
                np.clip(
                    np.median(residual) * len(fit) / (len(fit) + 100),
                    -MAX_CORRECTION[stat],
                    MAX_CORRECTION[stat],
                )
            )
            for offset in (0.0, correction):
                error = float(np.mean(np.abs(fit.actual - _prediction(fit, weight, offset))))
                candidates.append((error, weight, offset))
        _, weight, correction = min(candidates, key=lambda item: item[0])
        baseline = float(np.mean(np.abs(test.actual - test.base)))
        candidate = float(np.mean(np.abs(test.actual - _prediction(test, weight, correction))))
        accepted = baseline - candidate >= max(0.02, baseline * 0.02)
        result.update(
            status="Aplicado" if accepted else "Modelo base mantido",
            weight=weight,
            correction=correction,
            fit_end=str(fit.day.max()),
            test_start=boundary,
            test_end=str(test.day.max()),
            test_rows=len(test),
            base_mae=baseline,
            candidate_mae=candidate,
            improvement=baseline - candidate,
        )
    if any(item["status"] == "Aplicado" for item in report["stats"].values()):
        report["status"] = "Ajustes validados"
    elif any(item["status"] == "Modelo base mantido" for item in report["stats"].values()):
        report["status"] = "Modelo base mantido"
    return report


def refresh_prop_feedback(path: str | Path, before_day: str | None = None) -> dict:
    from .analysis_archive import archive_path, connect_archive

    day = before_day or utc_now().astimezone(EASTERN).date().isoformat()
    previous = get_state(path, "props_feedback", {})
    ledger = []
    if archive_path(path).exists():
        with connect_archive(path) as connection:
            for name in ("daily_snapshots", "snapshot_outcomes"):
                ledger.append(connection.execute(f"SELECT COUNT(*),MAX(rowid) FROM {name}").fetchone())
    source_version = json.dumps([VERSION, day, ledger])
    if previous.get("source_version") == source_version:
        return previous
    table = feedback_rows(path, day)
    fingerprint = hashlib.sha256(
        VERSION.encode() + day.encode() + pd.util.hash_pandas_object(table, index=False).values.tobytes()
    ).hexdigest()
    if previous.get("data_hash") == fingerprint:
        previous["source_version"] = source_version
        set_state(path, "props_feedback", previous)
        return previous
    report = evaluate_feedback(table, day)
    report.update(data_hash=fingerprint, id=VERSION + "-" + fingerprint[:16], source_version=source_version)
    set_state(path, "props_feedback", report)
    return report


def with_prop_feedback(bundle: PropsBundle, path: str | Path, day: str) -> PropsBundle:
    report = refresh_prop_feedback(path, day)
    return replace(bundle, manifest={**bundle.manifest, "feedback": report})
