"""Contexto factual preservado na captura e comparação explícita com uma linha."""

from __future__ import annotations

import math

import pandas as pd

from .prop_probability import count_distribution


def capture_factors(row: pd.Series, history: pd.DataFrame | None = None) -> dict:
    def number(key):
        value = row.get(key)
        return float(value) if pd.notna(value) and math.isfinite(float(value)) else None

    factors = dict(
        rest_days=number("rest"),
        home=bool(row.get("is_home", False)),
        recent={
            stat: {"last5": number(stat + "_mean5"), "last10": number(stat + "_mean10")}
            for stat in ("pts", "reb", "ast")
        },
        opponent_allowed={stat: number("opponent_" + stat + "_10") for stat in ("pts", "reb", "ast")},
        note="Contexto observado antes da partida; não representa contribuição causal de cada variável",
    )
    if history is not None and not history.empty:
        before = history.loc[
            history.player_id.eq(row["player_id"])
            & pd.to_datetime(history.game_date).lt(pd.Timestamp(row["game_date"]))
        ].sort_values("game_date")
        current = before.loc[before.season.eq(row["season"])]
        factors["season"] = dict(
            games=len(current),
            means={
                stat: float(current[stat].mean()) if len(current) else None for stat in ("pts", "reb", "ast")
            },
        )
        factors["recent_games"] = [
            dict(
                day=pd.Timestamp(game.game_date).date().isoformat(),
                minutes=float(game.minutes),
                **{stat: int(getattr(game, stat)) for stat in ("pts", "reb", "ast")},
            )
            for game in before.tail(10).itertuples(index=False)
        ]
    return factors


def line_context(player: dict, stat: str, line: float) -> dict:
    if not math.isfinite(float(line)) or line < 0:
        raise ValueError("Linha inválida.")
    recent = player.get("factors", {}).get("recent_games", [])
    values = [game[stat] for game in recent if stat in game and pd.notna(game[stat])]
    return dict(
        over_min=math.floor(line) + 1,
        under_max=math.ceil(line) - 1,
        push=int(line) if float(line).is_integer() else None,
        sample=len(values),
        recent_over=sum(value > line for value in values),
        recent_under=sum(value < line for value in values),
        recent_push=sum(value == line for value in values),
    )


def projection_components(estimate: dict) -> list[dict]:
    """Decomposição aritmética preservada, sem atribuição causal às features."""
    bayes, ml = estimate.get("bayes"), estimate.get("xgboost")
    if bayes is None or ml is None or "residual_correction" not in estimate:
        return []
    weight = float(estimate["ml_weight"])
    return [
        {"Componente": "Bayes", "Valor": bayes, "Peso": 1 - weight, "Parcela": (1 - weight) * bayes},
        {"Componente": "XGBoost", "Valor": ml, "Peso": weight, "Parcela": weight * ml},
        {
            "Componente": "Ajuste pelos resultados anteriores",
            "Valor": estimate["residual_correction"],
            "Peso": 1.0,
            "Parcela": estimate["residual_correction"],
        },
    ]


def compare_line(estimate: dict, line: float) -> dict | None:
    line = float(line)
    if not math.isfinite(line) or line < 0:
        raise ValueError("A linha deve ser um número não negativo.")
    shape, mean = estimate.get("dispersion_shape"), estimate.get("projected")
    if (
        math.isclose(line % 1, 0.5)
        and math.isclose(line, float(estimate.get("line", -1)))
        and all(k in estimate for k in ("over", "under"))
    ):
        over, under = float(estimate["over"]), float(estimate["under"])
        if all(math.isfinite(p) and 0 <= p <= 1 for p in (over, under)) and math.isclose(over + under, 1):
            return dict(over=over, under=under, push=0.0)
    if shape is None or mean is None:
        return None
    if (
        not math.isfinite(float(shape))
        or not math.isfinite(float(mean))
        or float(shape) <= 0
        or float(mean) < 0
    ):
        return None
    distribution = count_distribution(float(mean), float(shape))
    return dict(
        over=float(distribution.sf(math.floor(line))),
        under=float(distribution.cdf(math.ceil(line) - 1)),
        push=float(distribution.pmf(int(line))) if line.is_integer() else 0.0,
    )
