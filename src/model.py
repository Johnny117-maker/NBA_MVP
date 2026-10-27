from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import pregame_scoring_averages

FEATURE_NAMES = [
    "net_rating_diff",
    "form_diff",
    "rest_diff",
    "off_rating_diff",
    "defensive_edge",
]

FEATURE_LABELS = {
    "net_rating_diff": "Diferença de Net Rating",
    "form_diff": "Forma recente",
    "rest_diff": "Dias de descanso",
    "off_rating_diff": "Eficiência ofensiva",
    "defensive_edge": "Eficiência defensiva",
}

SCORE_MODEL_VERSION = 2
SCORE_FEATURE_NAMES = [
    *FEATURE_NAMES,
    "home_off_rating",
    "away_off_rating",
    "home_def_rating",
    "away_def_rating",
    "home_points_avg10",
    "away_points_avg10",
]


@dataclass
class ModelBundle:
    win_model: Pipeline
    home_score_model: Pipeline
    away_score_model: Pipeline
    metrics: dict[str, float]
    residual_std_home: float
    residual_std_away: float


@dataclass(frozen=True)
class GamePrediction:
    home_win_probability: float
    away_win_probability: float
    home_score: float
    away_score: float
    home_score_low: float
    home_score_high: float
    away_score_low: float
    away_score_high: float
    confidence: str
    factors: list[tuple[str, float]]


def build_features(games: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "net_rating_diff": games["home_net_rating"] - games["away_net_rating"],
            "form_diff": games["home_last10_win_pct"] - games["away_last10_win_pct"],
            "rest_diff": games["home_rest_days"] - games["away_rest_days"],
            "off_rating_diff": games["home_off_rating"] - games["away_off_rating"],
            "defensive_edge": games["away_def_rating"] - games["home_def_rating"],
        },
        index=games.index,
    )


def build_score_features(games: pd.DataFrame) -> pd.DataFrame:
    features = build_features(games)
    for side in ("home", "away"):
        for rating in ("off_rating", "def_rating"):
            features[f"{side}_{rating}"] = games[f"{side}_{rating}"]
    averages = pregame_scoring_averages(games)
    for column in averages:
        features[column] = averages[column].to_numpy()
    return features[SCORE_FEATURE_NAMES]


def temporal_split_index(games: pd.DataFrame) -> int:
    """Reserva aproximadamente 20% dos jogos, mantendo datas completas."""
    dates = pd.to_datetime(games["game_date"]).dt.normalize()
    if dates.nunique() < 2:
        raise ValueError("São necessárias pelo menos duas datas para validar o modelo.")
    boundary = dates.iloc[min(int(len(games) * 0.8), len(games) - 1)]
    if boundary == dates.iloc[0]:
        boundary = dates[dates.gt(boundary)].iloc[0]
    return int(dates.lt(boundary).sum())


def _classification_pipeline() -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=1_000, random_state=42)),
        ]
    )


def _regression_pipeline() -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=2.0))])


def train_models(games: pd.DataFrame) -> ModelBundle:
    if len(games) < 50:
        raise ValueError("São necessários pelo menos 50 jogos para treinar o modelo.")

    ordered = games.sort_values("game_date").reset_index(drop=True)
    features = build_features(ordered)
    score_features = build_score_features(ordered)
    home_win = ordered["home_win"].astype(int)
    split = temporal_split_index(ordered)

    x_train, x_test = features.iloc[:split], features.iloc[split:]
    y_train, y_test = home_win.iloc[:split], home_win.iloc[split:]

    evaluation_win_model = _classification_pipeline().fit(x_train, y_train)
    probabilities = evaluation_win_model.predict_proba(x_test)[:, 1]
    classifications = (probabilities >= 0.5).astype(int)

    evaluation_home_score = _regression_pipeline().fit(
        score_features.iloc[:split], ordered["home_points"].iloc[:split]
    )
    evaluation_away_score = _regression_pipeline().fit(
        score_features.iloc[:split], ordered["away_points"].iloc[:split]
    )
    predicted_home = evaluation_home_score.predict(score_features.iloc[split:])
    predicted_away = evaluation_away_score.predict(score_features.iloc[split:])

    metrics = {
        "score_model_version": float(SCORE_MODEL_VERSION),
        "score_feature_count": float(len(SCORE_FEATURE_NAMES)),
        "accuracy": float(accuracy_score(y_test, classifications)),
        "log_loss": float(log_loss(y_test, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y_test, probabilities)),
        "home_points_mae": float(
            mean_absolute_error(ordered["home_points"].iloc[split:], predicted_home)
        ),
        "away_points_mae": float(
            mean_absolute_error(ordered["away_points"].iloc[split:], predicted_away)
        ),
    }

    residual_std_home = float(
        np.std(ordered["home_points"].iloc[split:].to_numpy() - predicted_home)
    )
    residual_std_away = float(
        np.std(ordered["away_points"].iloc[split:].to_numpy() - predicted_away)
    )

    return ModelBundle(
        win_model=clone(evaluation_win_model).fit(features, home_win),
        home_score_model=clone(evaluation_home_score).fit(
            score_features, ordered["home_points"]
        ),
        away_score_model=clone(evaluation_away_score).fit(
            score_features, ordered["away_points"]
        ),
        metrics=metrics,
        residual_std_home=max(residual_std_home, 5.0),
        residual_std_away=max(residual_std_away, 5.0),
    )


def matchup_features(
    home: dict[str, float],
    away: dict[str, float],
    home_rest_days: int,
    away_rest_days: int,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "net_rating_diff": home["net_rating"] - away["net_rating"],
                "form_diff": home["win_pct"] - away["win_pct"],
                "rest_diff": home_rest_days - away_rest_days,
                "off_rating_diff": home["off_rating"] - away["off_rating"],
                "defensive_edge": away["def_rating"] - home["def_rating"],
            }
        ]
    )


def _factor_contributions(model: Pipeline, features: pd.DataFrame) -> list[tuple[str, float]]:
    scaler: StandardScaler = model.named_steps["scale"]
    classifier: LogisticRegression = model.named_steps["model"]
    scaled = scaler.transform(features)[0]
    coefficients = classifier.coef_[0]
    contributions = scaled * coefficients
    result = [
        (FEATURE_LABELS[name], float(value))
        for name, value in zip(FEATURE_NAMES, contributions, strict=True)
    ]
    return sorted(result, key=lambda item: abs(item[1]), reverse=True)


def matchup_score_features(
    home: dict[str, float],
    away: dict[str, float],
    home_rest_days: int,
    away_rest_days: int,
) -> pd.DataFrame:
    features = matchup_features(home, away, home_rest_days, away_rest_days)
    for side, snapshot in (("home", home), ("away", away)):
        for rating in ("off_rating", "def_rating"):
            features[f"{side}_{rating}"] = snapshot[rating]
        features[f"{side}_points_avg10"] = snapshot["points_for"]
    return features[SCORE_FEATURE_NAMES]


def predict_game(
    bundle: ModelBundle,
    home: dict[str, float],
    away: dict[str, float],
    home_rest_days: int = 2,
    away_rest_days: int = 2,
) -> GamePrediction:
    features = matchup_features(home, away, home_rest_days, away_rest_days)
    score_features = matchup_score_features(home, away, home_rest_days, away_rest_days)
    home_probability = float(bundle.win_model.predict_proba(features)[0, 1])
    predicted_home = float(bundle.home_score_model.predict(score_features)[0])
    predicted_away = float(bundle.away_score_model.predict(score_features)[0])

    margin = abs(home_probability - 0.5)
    confidence = "Baixa" if margin < 0.08 else "Média" if margin < 0.18 else "Alta"

    return GamePrediction(
        home_win_probability=home_probability,
        away_win_probability=1.0 - home_probability,
        home_score=predicted_home,
        away_score=predicted_away,
        home_score_low=max(0.0, predicted_home - 1.28 * bundle.residual_std_home),
        home_score_high=predicted_home + 1.28 * bundle.residual_std_home,
        away_score_low=max(0.0, predicted_away - 1.28 * bundle.residual_std_away),
        away_score_high=predicted_away + 1.28 * bundle.residual_std_away,
        confidence=confidence,
        factors=_factor_contributions(bundle.win_model, features),
    )
