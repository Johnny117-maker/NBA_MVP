"""Contexto factual preservado na captura e comparação explícita com uma linha."""

from __future__ import annotations

import math

import pandas as pd
from scipy.stats import nbinom


def capture_factors(row: pd.Series) -> dict:
    def number(key):
        value = row.get(key)
        return float(value) if pd.notna(value) and math.isfinite(float(value)) else None

    return dict(
        rest_days=number("rest"),
        home=bool(row.get("is_home", False)),
        recent={
            stat: {"last5": number(stat + "_mean5"), "last10": number(stat + "_mean10")}
            for stat in ("pts", "reb", "ast")
        },
        opponent_allowed={stat: number("opponent_" + stat + "_10") for stat in ("pts", "reb", "ast")},
        note="Contexto observado antes da partida; não representa contribuição causal de cada variável",
    )


def compare_line(estimate: dict, line: float) -> dict | None:
    line = float(line)
    if not math.isfinite(line) or line < 0:
        raise ValueError("A linha deve ser um número não negativo.")
    shape, mean = estimate.get("dispersion_shape"), estimate.get("projected")
    if shape is None or mean is None:
        if (
            math.isclose(line % 1, 0.5)
            and math.isclose(line, float(estimate.get("line", -1)))
            and all(k in estimate for k in ("over", "under"))
        ):
            return dict(over=estimate["over"], under=estimate["under"], push=0.0)
        return None
    if (
        not math.isfinite(float(shape))
        or not math.isfinite(float(mean))
        or float(shape) <= 0
        or float(mean) < 0
    ):
        return None
    distribution = nbinom(float(shape), float(shape) / (float(shape) + max(float(mean), 0.001)))
    return dict(
        over=float(distribution.sf(math.floor(line))),
        under=float(distribution.cdf(math.ceil(line) - 1)),
        push=float(distribution.pmf(int(line))) if line.is_integer() else 0.0,
    )
