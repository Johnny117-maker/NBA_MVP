"""Avaliação de capturas reais, com resultados separados e comparação na mesma amostra."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis_archive import archive_path, connect_archive, read_snapshots
from .prop_training import STATS


def capture_integrity(snapshot: dict) -> tuple[bool, str]:
    try:
        captured, kickoff = pd.Timestamp(snapshot["captured_at"]), pd.Timestamp(snapshot["kickoff"])
        day = pd.Timestamp(snapshot["day"]).normalize()
        cutoffs = [snapshot.get("history_end"), snapshot.get("model", {}).get("train_end")]
        if captured.tzinfo is None or kickoff.tzinfo is None or pd.isna(captured) or pd.isna(kickoff):
            return False, "Horário pré-jogo não verificável"
        if captured >= kickoff or snapshot.get("state") != "pre":
            return False, "Captura fora do pré-jogo"
        if not cutoffs[0] or any(value and pd.Timestamp(value).normalize() >= day for value in cutoffs):
            return False, "Corte de dados não é anterior ao jogo"
        return True, "Pré-jogo verificável"
    except (ValueError, TypeError, KeyError):
        return False, "Proveniência incompleta"


def performance_rows(path: str | Path, start: str, end: str) -> pd.DataFrame:
    if start > end or not archive_path(path).exists():
        return pd.DataFrame()
    snapshots = [s for s in read_snapshots(path, limit=4000) if start <= s["day"] <= end]
    with connect_archive(path) as connection:
        results = connection.execute(
            "SELECT o.snapshot_id,o.player_id,o.payload FROM snapshot_outcomes o "
            "JOIN daily_snapshots s ON s.id=o.snapshot_id WHERE s.day BETWEEN ? AND ? "
            "AND o.rowid=(SELECT MAX(n.rowid) FROM snapshot_outcomes n "
            "WHERE n.snapshot_id=o.snapshot_id AND n.player_id=o.player_id)",
            (start, end),
        ).fetchall()
    outcomes = {(sid, pid): json.loads(body) for sid, pid, body in results}
    rows = []
    for snapshot in snapshots:
        eligible, provenance = capture_integrity(snapshot)
        for player in snapshot["players"]:
            outcome = outcomes.get((snapshot["id"], player["player_id"]), {})
            confirmed = bool(outcome.get("confirmed_final"))
            played = outcome.get("status") == "Jogou" and eligible and confirmed
            status = outcome.get("status", "Aguardando resultado")
            if outcome and not confirmed:
                status = "Aguardando conferência final"
            for stat in STATS:
                estimate = player["stats"].get(stat, {})
                if "projected" not in estimate:
                    continue
                actual = (outcome.get("actual") or {}).get(stat) if played else None
                row = dict(
                    snapshot_id=snapshot["id"],
                    day=snapshot["day"],
                    game=snapshot["game_key"],
                    player=player["name"],
                    team=player["team"],
                    stat=stat,
                    model=snapshot["model"].get("id", "Sem identificação"),
                    status=status if eligible else provenance,
                    pre_game_valid=eligible,
                    actual=actual,
                    projected=estimate["projected"],
                    bayes=estimate.get("bayes"),
                    xgboost=estimate.get("xgboost"),
                    base=estimate.get("base_projected"),
                    low=estimate.get("low"),
                    high=estimate.get("high"),
                    line=estimate.get("line"),
                    over=estimate.get("over"),
                    under=estimate.get("under"),
                    reference_over=estimate.get("reference_over"),
                    minutes=player.get("minutes"),
                    actual_minutes=outcome.get("minutes") if eligible and confirmed else None,
                )
                rows.append(row)
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    numeric = [
        "actual",
        "projected",
        "bayes",
        "xgboost",
        "base",
        "low",
        "high",
        "line",
        "over",
        "under",
        "reference_over",
        "minutes",
        "actual_minutes",
    ]
    table[numeric] = table[numeric].apply(pd.to_numeric, errors="coerce")
    table[numeric] = table[numeric].replace([np.inf, -np.inf], np.nan)
    table.loc[table.actual.lt(0), "actual"] = np.nan
    table["error"] = table.projected - table.actual
    return table


def quantity_metrics(table: pd.DataFrame) -> dict:
    if table.empty:
        return dict(n=0, mae=None, bias=None, coverage=None)
    valid = table.dropna(subset=["actual", "projected"])
    if valid.empty:
        return dict(n=0, mae=None, bias=None, coverage=None)
    error = valid.projected - valid.actual
    intervals = valid.dropna(subset=["low", "high"])
    intervals = intervals.loc[intervals.low.le(intervals.high)]
    coverage = (
        float(intervals.actual.between(intervals.low, intervals.high).mean()) if len(intervals) else None
    )
    return dict(n=len(valid), mae=float(error.abs().mean()), bias=float(error.mean()), coverage=coverage)


def probability_rows(table: pd.DataFrame, *, side: str = "over") -> pd.DataFrame:
    if side not in {"over", "under"}:
        raise ValueError("Lado deve ser over ou under.")
    if table.empty:
        return table.copy()
    valid = table.dropna(subset=["actual", "line", "over"]).copy()
    valid["under"] = valid["under"].fillna(1 - valid.over) if "under" in valid else 1 - valid.over
    # Avalia somente linhas de meia unidade: empate/devolução não vira derrota.
    valid = valid.loc[
        valid.over.between(0, 1)
        & valid.under.between(0, 1)
        & np.isclose(valid.over + valid.under, 1)
        & valid.line.ge(0)
        & np.isclose(valid.line % 1, 0.5)
        & valid.actual.ge(0)
        & np.isclose(valid.actual % 1, 0)
    ].copy()
    valid["observed_over"] = valid.actual.gt(valid.line).astype(float)
    valid["forecast_probability"] = valid[side]
    valid["observed_event"] = valid.observed_over if side == "over" else 1 - valid.observed_over
    return valid


def probability_metrics(table: pd.DataFrame, *, side: str = "over") -> dict:
    valid = probability_rows(table, side=side)
    if valid.empty:
        return dict(n=0, brier=None, log_loss=None)
    probability = valid.forecast_probability.clip(1e-12, 1 - 1e-12)
    actual = valid.observed_event
    return dict(
        n=len(valid),
        brier=float(((valid.forecast_probability - actual) ** 2).mean()),
        log_loss=float(-(actual * np.log(probability) + (1 - actual) * np.log(1 - probability)).mean()),
    )


def calibration_bins(table: pd.DataFrame, *, side: str = "over") -> pd.DataFrame:
    valid = probability_rows(table, side=side)
    if valid.empty:
        return pd.DataFrame()
    valid["bucket"] = np.minimum((valid.forecast_probability * 10).astype(int), 9)
    grouped = (
        valid.groupby("bucket")
        .agg(
            n=("over", "size"),
            predicted=("forecast_probability", "mean"),
            observed=("observed_event", "mean"),
        )
        .reset_index()
    )
    # Intervalo de Wilson de 95% deixa a incerteza da frequência observada explícita.
    z, n, p = 1.96, grouped.n, grouped.observed
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    grouped["low"], grouped["high"] = center - margin, center + margin
    return grouped


def paired_comparison(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return pd.DataFrame()
    valid = table.dropna(subset=["actual", "bayes", "xgboost", "projected"])
    if valid.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Modelo": label,
                "Erro médio": float((valid[key] - valid.actual).abs().mean()),
                "Amostra": len(valid),
            }
            for label, key in (
                ("Bayes", "bayes"),
                ("XGBoost", "xgboost"),
                ("Projeção utilizada", "projected"),
            )
        ]
    )
