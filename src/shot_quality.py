"""xP por localização, distinto de shot quality com tracking de defensores."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

FEATURES = ["shot_distance", "angle", "shot_value", "period", "seconds_in_period"]


def shot_features(rows: pd.DataFrame) -> pd.DataFrame:
    data = rows.copy()
    data["angle"] = np.degrees(np.arctan2(data["loc_x_ft"].abs(), data["loc_y_ft"]))
    data["shot_value"] = np.where(data["shot_type"].str.startswith("3PT"), 3, 2)
    data["seconds_in_period"] = 60 * data["minutes_remaining"] + data["seconds_remaining"]
    if not np.isfinite(data[FEATURES].to_numpy(dtype=float)).all():
        raise ValueError("Coordenadas ou características de arremesso inválidas.")
    return data


def train_location_quality(path: str | Path, output: Path, before_day: str) -> dict:
    from xgboost import XGBClassifier

    with sqlite3.connect(path) as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_shots'"
        ).fetchone():
            raise ValueError("Colete arremessos no mapa antes de treinar o modelo de xP.")
        rows = pd.read_sql_query(
            "SELECT game_date,shot_distance,loc_x_ft,loc_y_ft,shot_type,period,"
            "minutes_remaining,seconds_remaining,shot_made FROM player_shots "
            "WHERE date(game_date)<? AND shot_attempted=1 "
            "ORDER BY game_date DESC,game_id DESC,game_event_id DESC LIMIT 60000",
            connection,
            params=(before_day,),
        )
    data = shot_features(rows).sort_values("game_date")
    dates = sorted(data["game_date"].unique())
    if len(data) < 1000 or len(dates) < 10 or not set(data["shot_made"].unique()).issubset({0, 1}):
        raise ValueError("xP exige ao menos 1.000 tentativas válidas e 10 datas, com acertos e erros.")
    split = dates[int(len(dates) * 0.8)]
    train, test = data.loc[data["game_date"].lt(split)], data.loc[data["game_date"].ge(split)]
    if train["shot_made"].nunique() < 2:
        raise ValueError("O treino precisa conter acertos e erros.")
    model = XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        min_child_weight=30,
        reg_lambda=5,
        tree_method="hist",
        n_jobs=2,
        random_state=42,
    )
    model.fit(train[FEATURES], train["shot_made"])
    prediction = model.predict_proba(test[FEATURES])[:, 1]
    baseline = np.full(len(test), float(train["shot_made"].mean()))
    manifest = {
        "version": "xp-location-v1",
        "features": FEATURES,
        "rows": len(data),
        "history_end": str(data["game_date"].max())[:10],
        "test_start": str(split)[:10],
        "brier": float(brier_score_loss(test["shot_made"], prediction)),
        "baseline_brier": float(brier_score_loss(test["shot_made"], baseline)),
        "log_loss": float(log_loss(test["shot_made"], prediction, labels=[0, 1])),
        "tracking": False,
        "description": "xP de localização; sem distância de defensor ou relógio de posse",
    }
    model.fit(data[FEATURES], data["shot_made"])
    output.mkdir(parents=True, exist_ok=True)
    model.save_model(output / "shot_location.json")
    (output / "shot_location_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def expected_points(output: Path, *, distance: float, angle: float, value: int) -> dict:
    from xgboost import XGBClassifier

    if not 0 <= distance <= 90 or not 0 <= angle <= 180 or value not in {2, 3}:
        raise ValueError("Distância, ângulo ou valor do arremesso inválidos.")
    model = XGBClassifier()
    model.load_model(output / "shot_location.json")
    row = pd.DataFrame(
        [
            {
                "shot_distance": distance,
                "angle": angle,
                "shot_value": value,
                "period": 2,
                "seconds_in_period": 360,
            }
        ]
    )
    probability = float(model.predict_proba(row[FEATURES])[0, 1])
    return {"make_probability": probability, "expected_points": value * probability}
