"""XGBoost de contagens com validação temporal e referência Gamma-Poisson explícita."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import nbinom
from sklearn.metrics import mean_absolute_error

from .daily_games import recent_training_sample
from .live_types import utc_now
from .player_metrics import add_efficiency_metrics

VERSION = "props-xgb-audit-v3"
STATS = ("pts", "reb", "ast")
LEAGUE_RATE_PRIORS = {"pts": 0.5, "reb": 0.22, "ast": 0.11}
FEATURES = [
    "minutes_5",
    "minutes_10",
    "rest",
    "is_home",
    "history_games",
    "ts_10",
    "usage_10",
    "assist_ratio_10",
    "turnover_ratio_10",
    *[f"{s}_{f}" for s in STATS for f in ("mean5", "mean10", "rate5", "rate10", "std10", "dynamic")],
    *[f"opponent_{s}_10" for s in STATS],
]


def load_research_history(path: str | Path, before_day: str) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame()
    with sqlite3.connect(path, timeout=15) as connection:
        rows = pd.read_sql_query(
            "SELECT * FROM player_game_stats WHERE minutes>0 AND date(game_date)<? "
            "ORDER BY game_date DESC,game_id DESC LIMIT 42000",
            connection,
            params=(before_day,),
        )
    if rows.empty:
        return rows
    rows["game_date"] = pd.to_datetime(rows["game_date"]).dt.normalize()
    return recent_training_sample(rows, max_rows=40000).reset_index(drop=True)


def _dynamic_before(group: pd.DataFrame, stat: str) -> pd.Series:
    mean, variance = math.log(LEAGUE_RATE_PRIORS[stat]), 1.0
    result = []
    for count, minutes in zip(group[stat], group["minutes"], strict=True):
        variance += 0.015
        result.append(math.exp(mean + variance / 2))
        if pd.notna(count) and pd.notna(minutes) and minutes > 0:
            observation = math.log((float(count) + 0.5) / (float(minutes) + 1))
            noise = 1 / (float(count) + 0.5)
            gain = variance / (variance + noise)
            mean += gain * (observation - mean)
            variance *= 1 - gain
    return pd.Series(result, index=group.index, dtype=float)


def feature_table(history: pd.DataFrame, future: pd.DataFrame | None = None) -> pd.DataFrame:
    """Cada feature da data D usa somente dados anteriores a D; sem IDs como features.

    Os alvos futuros são NaN e nunca são convertidos em observações de produção.
    Uma linha por jogador/data é exigida para impedir vazamento em duplicatas.
    """
    data = history.copy()
    if future is not None and not future.empty:
        data = pd.concat([data, future], ignore_index=True)
    data["game_date"] = pd.to_datetime(data["game_date"]).dt.normalize()
    if data.duplicated(["player_id", "game_date"]).any():
        raise ValueError("Há mais de uma observação do mesmo jogador na mesma data.")
    data = data.sort_values(["player_id", "game_date"]).reset_index(drop=True)
    data = add_efficiency_metrics(data)
    groups = data.groupby("player_id", sort=False)
    data["history_games"] = groups.cumcount()
    data["rest"] = groups["game_date"].diff().dt.days.clip(1, 14)
    for window in (5, 10):
        data[f"minutes_{window}"] = groups["minutes"].transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean()
        )
    data["minutes_3"] = groups["minutes"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    data["minutes_std10"] = groups["minutes"].transform(lambda s: s.shift(1).rolling(10, min_periods=2).std())
    data["minutes_trend"] = data["minutes_3"] - data["minutes_10"]
    for source, name in (
        ("true_shooting_pct", "ts"),
        ("usage_pct", "usage"),
        ("assist_ratio", "assist_ratio"),
        ("turnover_ratio", "turnover_ratio"),
    ):
        data[name + "_10"] = groups[source].transform(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    data["expected_minutes"] = (0.7 * data["minutes_5"] + 0.3 * data["minutes_10"]).clip(0, 48)
    for stat in STATS:
        data["_rate"] = data[stat] / data["minutes"].replace(0, np.nan)
        for window in (5, 10):
            data[f"{stat}_mean{window}"] = groups[stat].transform(
                lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean()
            )
            data[f"{stat}_rate{window}"] = data.groupby("player_id")["_rate"].transform(
                lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean()
            )
        data[f"{stat}_std10"] = groups[stat].transform(lambda s: s.shift(1).rolling(10, min_periods=2).std())
        data[f"{stat}_dynamic"] = pd.concat([_dynamic_before(g, stat) for _, g in groups]).sort_index()
        counts = groups[stat].transform(lambda s: s.shift(1).rolling(10, min_periods=1).sum())
        minutes = groups["minutes"].transform(lambda s: s.shift(1).rolling(10, min_periods=1).sum())
        data[f"{stat}_alpha"] = counts + 20 * LEAGUE_RATE_PRIORS[stat]
        data[f"{stat}_beta"] = minutes + 20
        data[f"{stat}_bayes"] = data[f"{stat}_alpha"] / data[f"{stat}_beta"] * data["expected_minutes"]
    # Agrega por data ANTES do shift: nenhum colega/adversário da mesma rodada vaza para a previsão.
    observed = data.loc[data["minutes"].notna()]
    allowed = observed.groupby(["opponent", "game_date"], as_index=False)[list(STATS)].sum()
    allowed = allowed.sort_values(["opponent", "game_date"])
    for stat in STATS:
        allowed[f"opponent_{stat}_10"] = allowed.groupby("opponent")[stat].transform(
            lambda s: s.rolling(10, min_periods=1).mean()
        )
    # Merge temporal estritamente anterior, inclusive para equipes sem partida na data alvo.
    for stat in STATS:
        data[f"opponent_{stat}_10"] = np.nan
    for opponent, indexes in data.groupby("opponent").groups.items():
        reference = allowed.loc[allowed["opponent"].eq(opponent)].sort_values("game_date")
        if reference.empty:
            continue
        left = data.loc[indexes, ["game_date"]].sort_values("game_date")
        merged = pd.merge_asof(
            left,
            reference[["game_date", *[f"opponent_{s}_10" for s in STATS]]],
            on="game_date",
            allow_exact_matches=False,
        )
        data.loc[left.index, [f"opponent_{s}_10" for s in STATS]] = merged[
            [f"opponent_{s}_10" for s in STATS]
        ].to_numpy()
    data["is_home"] = data["is_home"].astype(float)
    return data.drop(columns="_rate")


@dataclass
class PropsBundle:
    models: dict
    manifest: dict
    minutes_model: Any = None

    def predict(self, features: pd.DataFrame, stat: str) -> np.ndarray:
        return np.clip(self.models[stat].predict(features[FEATURES].astype(float)), 0, None)


def _fit_props(history: pd.DataFrame, *, estimators: int = 120) -> PropsBundle:
    from xgboost import XGBRegressor

    table = feature_table(history)
    table = table.loc[table["history_games"].ge(5)].copy()
    dates = sorted(table["game_date"].unique())
    if len(table) < 1000 or len(dates) < 20:
        raise ValueError("XGBoost exige ao menos 1.000 observações e 20 datas elegíveis.")
    calibration_start, test_start = dates[int(len(dates) * 0.6)], dates[int(len(dates) * 0.8)]
    fit = table.loc[table["game_date"].lt(calibration_start)]
    calibration = table.loc[table["game_date"].ge(calibration_start) & table["game_date"].lt(test_start)]
    test = table.loc[table["game_date"].ge(test_start)]
    config = {
        "objective": "count:poisson",
        "n_estimators": estimators,
        "max_depth": 3,
        "learning_rate": 0.05,
        "min_child_weight": 25,
        "subsample": 0.85,
        "colsample_bytree": 0.9,
        "reg_lambda": 5,
        "tree_method": "hist",
        "n_jobs": 2,
        "random_state": 42,
    }
    manifest: dict = {
        "version": VERSION,
        "created_at": utc_now().isoformat(),
        "features": FEATURES,
        "train_end": history["game_date"].max().date().isoformat(),
        "rows": len(table),
        "fit_end": fit["game_date"].max().date().isoformat(),
        "calibration_start": pd.Timestamp(calibration_start).date().isoformat(),
        "test_start": pd.Timestamp(test_start).date().isoformat(),
        "test_end": test["game_date"].max().date().isoformat(),
        "test_rows": len(test),
        "config": config,
        "metrics": {},
        "weights": {},
        "dispersion": {},
        "probability_status": "Experimental; avaliação de médias não calibra probabilidades Over/Under",
    }
    models = {}
    validation_predictions = {}
    for stat in STATS:
        model = XGBRegressor(**config)
        model.fit(fit[FEATURES].astype(float), fit[stat].astype(float))
        cal_ml = np.clip(model.predict(calibration[FEATURES].astype(float)), 0, None)
        cal_bayes = calibration[f"{stat}_bayes"].to_numpy()
        errors = {
            weight: mean_absolute_error(calibration[stat], (1 - weight) * cal_bayes + weight * cal_ml)
            for weight in (0.0, 0.25, 0.5, 0.75, 1.0)
        }
        weight = min(errors, key=lambda w: errors[w])
        if errors[weight] >= errors[0] * 0.99:
            weight = 0.0
        pred_ml = np.clip(model.predict(test[FEATURES].astype(float)), 0, None)
        baseline = test[f"{stat}_bayes"].to_numpy()
        projected = (1 - weight) * baseline + weight * pred_ml
        validation_predictions[stat] = projected
        manifest["weights"][stat] = weight
        manifest["metrics"][stat] = {
            "bayes_mae": float(mean_absolute_error(test[stat], baseline)),
            "xgb_mae": float(mean_absolute_error(test[stat], pred_ml)),
            "ensemble_mae": float(mean_absolute_error(test[stat], projected)),
            "calibration_mae": float(errors[weight]),
        }
        # Variância adicional calibrada somente no bloco de calibração, nunca no teste.
        cal_pred = (1 - weight) * cal_bayes + weight * cal_ml
        excess = max(0.1, float(np.mean((calibration[stat].to_numpy() - cal_pred) ** 2 - cal_pred)))
        shape = float(np.clip(float(np.mean(cal_pred)) ** 2 / excess, 1, 60))
        manifest["dispersion"][stat] = shape
        model.fit(table[FEATURES].astype(float), table[stat].astype(float))
        models[stat] = model
    from .minutes_model import train_minutes

    minutes, minutes_report = train_minutes(
        fit, calibration, test, table, validation_predictions, estimators=estimators
    )
    manifest["minutes_model"] = minutes_report
    manifest["metrics_basis"] = "Ensemble inclui ajuste de minutos quando validado; Bayes/XGB são referências"
    if minutes_report["active"]:
        for stat in STATS:
            manifest["metrics"][stat]["ensemble_mae_before_minutes"] = manifest["metrics"][stat][
                "ensemble_mae"
            ]
            manifest["metrics"][stat]["ensemble_mae"] = minutes_report["prop_guard"][stat][
                "minutes_adjusted_mae"
            ]
    return PropsBundle(models, manifest, minutes)


def train_props(history: pd.DataFrame, *, estimators: int = 120) -> PropsBundle:
    from .prop_validation import temporal_audit

    bundle = _fit_props(history, estimators=estimators)
    report, _ = temporal_audit(history, trainer=lambda prior: _fit_props(prior, estimators=estimators))
    bundle.manifest["validation"] = report
    bundle.manifest["metrics_basis"] = (
        "Métricas internas de desenvolvimento; a evidência independente está em validation. "
        "O teste externo avalia a política de treino em períodos anteriores ao modelo atual."
    )
    return bundle


def ensure_props_bundle(history: pd.DataFrame, root: Path) -> PropsBundle:
    from xgboost import XGBRegressor

    digest = hashlib.sha256(
        VERSION.encode() + pd.util.hash_pandas_object(history, index=False).values.tobytes()
    )
    model_id = VERSION + "-" + digest.hexdigest()[:16]
    directory = root / model_id
    if (directory / "manifest.json").exists():
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        models = {}
        for stat in STATS:
            model = XGBRegressor()
            model.load_model(directory / f"{stat}.json")
            models[stat] = model
        minutes = None
        if (directory / "minutes.json").exists():
            minutes = XGBRegressor()
            minutes.load_model(directory / "minutes.json")
        return PropsBundle(models, manifest, minutes)
    bundle = train_props(history)
    bundle.manifest["id"] = model_id
    bundle.manifest["data_hash"] = digest.hexdigest()
    temporary = root / (".training-" + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    for stat, model in bundle.models.items():
        model.save_model(temporary / f"{stat}.json")
    if bundle.minutes_model is not None:
        bundle.minutes_model.save_model(temporary / "minutes.json")
    (temporary / "manifest.json").write_text(json.dumps(bundle.manifest, indent=2), encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, directory)
    return bundle


def project_props(row: pd.Series, bundle: PropsBundle | None = None) -> dict:
    from .minutes_model import minutes_ratio, project_minutes

    minutes = project_minutes(
        row,
        bundle.minutes_model if bundle else None,
        bundle.manifest.get("minutes_model", {}) if bundle else {},
    )
    ratio = float(minutes_ratio(minutes["projected"], minutes["baseline"]))
    result: dict = {"minutes": minutes["projected"], "minutes_context": minutes, "stats": {}}
    for stat in STATS:
        bayes = float(row[f"{stat}_bayes"]) * ratio
        ml = float(bundle.predict(row.to_frame().T, stat)[0]) * ratio if bundle else None
        weight = float(bundle.manifest["weights"][stat]) if bundle else 0.0
        applied_weight = weight
        central = (1 - weight) * bayes + weight * ml if ml is not None else bayes
        base = central
        feedback = bundle.manifest.get("feedback", {}) if bundle else {}
        adjustment = feedback.get("stats", {}).get(stat, {})
        if adjustment.get("status") == "Aplicado":
            if adjustment.get("weight") is not None and ml is not None:
                adapted_weight = float(adjustment["weight"])
                applied_weight = adapted_weight
                central = (1 - adapted_weight) * bayes + adapted_weight * ml
            blend = central
            central = max(0.0, central + float(adjustment["correction"]))
        else:
            blend = central
        shape = float(bundle.manifest["dispersion"][stat]) if bundle else 4.0
        # Inclui incerteza posterior da taxa e sobredispersão por partida.
        posterior_shape = float(row[f"{stat}_alpha"])
        effective_shape = 1 / (1 / shape + 1 / posterior_shape)
        distribution = nbinom(effective_shape, effective_shape / (effective_shape + max(central, 0.001)))
        line = math.floor(bayes) + 0.5
        result["stats"][stat] = {
            "bayes": bayes,
            "xgboost": ml,
            "ml_weight": applied_weight,
            "base_ml_weight": weight,
            "residual_correction": central - blend,
            "projected": central,
            "base_projected": base,
            "feedback_id": feedback.get("id"),
            "feedback_correction": central - base,
            "dispersion_shape": effective_shape,
            "low": float(distribution.ppf(0.1)),
            "high": float(distribution.ppf(0.9)),
            "line": line,
            "over": float(distribution.sf(math.floor(line))),
            "under": float(distribution.cdf(math.floor(line))),
            "dynamic_rate": float(row[f"{stat}_dynamic"]),
        }
    return result
