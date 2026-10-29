"""Modelo de minutos condicionado à participação, validado em datas posteriores."""

from __future__ import annotations

import numpy as np
import pandas as pd

MINUTE_FEATURES = [
    "minutes_3",
    "minutes_5",
    "minutes_10",
    "minutes_std10",
    "minutes_trend",
    "rest",
    "is_home",
    "history_games",
    "usage_10",
]


def minutes_ratio(predicted, baseline):
    return np.clip(np.asarray(predicted) / np.maximum(np.asarray(baseline), 1), 0, 2)


def train_minutes(
    fit: pd.DataFrame,
    calibration: pd.DataFrame,
    validation: pd.DataFrame,
    all_rows: pd.DataFrame,
    prop_predictions: dict,
    *,
    estimators=120,
):
    from xgboost import XGBRegressor

    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=max(20, estimators),
        max_depth=2,
        learning_rate=0.06,
        min_child_weight=20,
        reg_lambda=8,
        tree_method="hist",
        n_jobs=2,
        random_state=42,
    )
    model.fit(fit[MINUTE_FEATURES].astype(float), fit.minutes.astype(float))
    cal_raw = np.clip(model.predict(calibration[MINUTE_FEATURES].astype(float)), 1, 48)
    val_raw = np.clip(model.predict(validation[MINUTE_FEATURES].astype(float)), 1, 48)
    cal_base, val_base = calibration.expected_minutes.to_numpy(), validation.expected_minutes.to_numpy()
    errors = {
        weight: float(np.mean(np.abs(calibration.minutes - ((1 - weight) * cal_base + weight * cal_raw))))
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0)
    }
    weight = min(errors, key=lambda value: errors[value])
    val_selected = (1 - weight) * val_base + weight * val_raw
    val_base_mae = float(np.mean(np.abs(validation.minutes - val_base)))
    val_mae = float(np.mean(np.abs(validation.minutes - val_selected)))
    active = bool(
        errors[0.0] - errors[weight] >= max(0.15, errors[0.0] * 0.02)
        and val_base_mae - val_mae >= max(0.15, val_base_mae * 0.02)
    )
    guard = {}
    for stat, predictions in prop_predictions.items():
        base = np.asarray(predictions)
        adjusted = base * minutes_ratio(val_selected, val_base)
        old = float(np.mean(np.abs(validation[stat] - base)))
        new = float(np.mean(np.abs(validation[stat] - adjusted)))
        guard[stat] = dict(base_mae=old, minutes_adjusted_mae=new)
        active = active and new <= old + max(0.02, old * 0.01)
    actual_weight = weight if active else 0.0
    residual = calibration.minutes.to_numpy() - ((1 - actual_weight) * cal_base + actual_weight * cal_raw)
    report = dict(
        version="minutes-xgb-v1",
        active=active,
        weight=actual_weight,
        status="XGBoost validado" if active else "Média recente mantida",
        fit_end=fit.game_date.max().date().isoformat(),
        calibration_start=calibration.game_date.min().date().isoformat(),
        validation_start=validation.game_date.min().date().isoformat(),
        validation_end=validation.game_date.max().date().isoformat(),
        validation_rows=len(validation),
        base_mae=val_base_mae,
        candidate_mae=val_mae,
        calibration_base_mae=errors[0.0],
        calibration_candidate_mae=errors[weight],
        residual_low=float(np.quantile(residual, 0.1)),
        residual_high=float(np.quantile(residual, 0.9)),
        prop_guard=guard,
        participation="Condicionado à participação; titularidade e restrições não confirmadas",
        evaluation="Calibração e validação temporal usadas na decisão; acompanhar resultados prospectivos",
    )
    model.fit(all_rows[MINUTE_FEATURES].astype(float), all_rows.minutes.astype(float))
    return model, report


def project_minutes(row: pd.Series, model, report: dict) -> dict:
    base = float(row["expected_minutes"])
    expected = base
    if model is not None and report.get("active") and float(row.get("history_games", 0)) >= 5:
        candidate = float(np.clip(model.predict(row.to_frame().T[MINUTE_FEATURES].astype(float))[0], 1, 48))
        expected = (1 - float(report["weight"])) * base + float(report["weight"]) * candidate
    return dict(
        projected=float(np.clip(expected, 1, 48)),
        baseline=base,
        low=max(0.0, min(expected, expected + float(report.get("residual_low", -6)))),
        high=min(48.0, max(expected, expected + float(report.get("residual_high", 6)))),
        status=report.get("status", "Média recente"),
        participation="Estimativa caso o jogador participe; escalação e limite de minutos não confirmados",
    )
