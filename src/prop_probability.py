"""Distribuição de contagens e ajuste de dispersão sem usar o teste externo."""

from __future__ import annotations

import numpy as np
from scipy.stats import nbinom


def count_distribution(mean, shape):
    mean, shape = np.broadcast_arrays(np.asarray(mean, dtype=float), np.asarray(shape, dtype=float))
    if not np.isfinite(mean).all() or not np.isfinite(shape).all() or (mean < 0).any() or (shape <= 0).any():
        raise ValueError("Média e dispersão inválidas para a distribuição de contagens.")
    return nbinom(shape, shape / (shape + mean))


def grid_scores(table, mean, base_shape: float, stat: str, scale: float) -> dict:
    mask = table.expected_minutes.ge(10).to_numpy()
    sample = table.loc[mask]
    mean = np.asarray(mean)[mask]
    if sample.empty:
        return dict(n=0, dates=0, forecasts=0, brier=None, log_loss=None)
    shape = 1 / (1 / (base_shape * scale) + 1 / sample[f"{stat}_alpha"].to_numpy())
    middle = np.floor(sample[f"{stat}_bayes"].to_numpy()) + 0.5
    offset = 5 if stat == "pts" else 2
    lines = np.stack([np.maximum(0.5, middle - offset), middle, middle + offset], axis=1)
    unique = np.ones_like(lines, dtype=bool)
    unique[:, 0] = lines[:, 0] != lines[:, 1]
    probability = count_distribution(mean[:, None], shape[:, None]).sf(np.floor(lines))[unique]
    actual = (sample[stat].to_numpy()[:, None] > lines)[unique].astype(float)
    clipped = np.clip(probability, 1e-12, 1 - 1e-12)
    return dict(
        n=len(sample),
        dates=int(sample.game_date.nunique()),
        forecasts=int(unique.sum()),
        brier=float(np.mean((probability - actual) ** 2)),
        log_loss=float(-np.mean(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped))),
    )


def fit_dispersion(calibration, validation, cal_mean, val_mean, base_shape: float, stat: str) -> dict:
    if not calibration.expected_minutes.ge(10).any() or not validation.expected_minutes.ge(10).any():
        return dict(
            status="Sem amostra elegível para calibrar probabilidades",
            scale=1.0,
            active=False,
            reference_over=0.5,
        )
    cal_scores = {
        scale: grid_scores(calibration, cal_mean, base_shape, stat, scale)
        for scale in (0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
    }
    candidate = min(cal_scores, key=lambda scale: cal_scores[scale]["brier"])
    raw = grid_scores(validation, val_mean, base_shape, stat, 1.0)
    adjusted = grid_scores(validation, val_mean, base_shape, stat, candidate)
    enough = all(score["n"] >= 400 and score["dates"] >= 14 for score in (raw, cal_scores[1.0]))
    accepted = bool(
        enough
        and candidate != 1.0
        and cal_scores[1.0]["brier"] - cal_scores[candidate]["brier"]
        >= max(0.0015, cal_scores[1.0]["brier"] * 0.01)
        and raw["brier"] - adjusted["brier"] >= max(0.0015, raw["brier"] * 0.01)
        and adjusted["log_loss"] <= raw["log_loss"] + 0.001
    )
    reference_line = np.floor(calibration[f"{stat}_bayes"].to_numpy()) + 0.5
    reference_probability = float(
        ((calibration[stat].to_numpy() > reference_line).sum() + 0.5) / (len(calibration) + 1)
    )
    return dict(
        status="Dispersão ajustada na validação interna" if accepted else "Distribuição original mantida",
        scale=candidate if accepted else 1.0,
        candidate_scale=candidate,
        active=accepted,
        reference_over=reference_probability,
        calibration_original=cal_scores[1.0],
        calibration_candidate=cal_scores[candidate],
        validation_original=raw,
        validation_candidate=adjusted,
        calibration_end=calibration.game_date.max().date().isoformat(),
        validation_start=validation.game_date.min().date().isoformat(),
        validation_end=validation.game_date.max().date().isoformat(),
        scope="Linhas estatísticas de meia unidade: referência e ±5 PTS ou ±2 REB/AST; "
        "não são linhas de casas",
    )
