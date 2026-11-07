from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import pregame_scoring_averages
from .team_strength import ELO_BASE, ensure_elo_columns

# Modelo de vencedor e margem: regressão da margem do mandante sobre a força
# relativa dos times. A probabilidade de vitória vem da mesma margem prevista
# (distribuição normal), então vencedor e placar nunca se contradizem.
FEATURE_NAMES = [
    "elo_diff",
    "net_rating_diff",
    "form_diff",
    "rest_diff",
]

FEATURE_LABELS = {
    "elo_diff": "Força do time (Elo)",
    "net_rating_diff": "Diferença de Net Rating",
    "form_diff": "Forma recente",
    "rest_diff": "Dias de descanso",
}

# Diferenças relativas usadas no modelo do total de pontos (versão anterior do
# vencedor). O total depende do nível absoluto de ataque e defesa, não só da
# diferença entre os times.
_RELATIVE_FEATURES = [
    "net_rating_diff",
    "form_diff",
    "rest_diff",
    "off_rating_diff",
    "defensive_edge",
]

SCORE_MODEL_VERSION = 3
SCORE_FEATURE_NAMES = [
    *_RELATIVE_FEATURES,
    "home_off_rating",
    "away_off_rating",
    "home_def_rating",
    "away_def_rating",
    "home_points_avg10",
    "away_points_avg10",
]

MARGIN_RIDGE_ALPHA = 10.0
TOTAL_RIDGE_ALPHA = 2.0
MIN_MARGIN_SIGMA = 8.0


class MarginWinModel:
    """Regressão da margem do mandante; `predict_proba` converte a margem em chance de vitória."""

    def __init__(self, pipeline: Pipeline, sigma: float):
        self.pipeline = pipeline
        self.sigma = float(sigma)

    @property
    def feature_names_in_(self) -> np.ndarray:
        return np.asarray(FEATURE_NAMES)

    def predict_margin(self, features: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict(features[FEATURE_NAMES])

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        home = norm.cdf(self.predict_margin(features) / self.sigma)
        return np.column_stack([1.0 - home, home])


@dataclass
class ModelBundle:
    win_model: MarginWinModel
    total_model: Pipeline
    metrics: dict[str, float]
    residual_std_home: float
    residual_std_away: float

    def predict_scores(self, features: pd.DataFrame, score_features: pd.DataFrame) -> pd.DataFrame:
        """Placar de cada time a partir da margem e do total previstos."""
        margin = self.win_model.predict_margin(features)
        total = self.total_model.predict(score_features[SCORE_FEATURE_NAMES])
        return pd.DataFrame(
            {
                "margin": margin,
                "home_points": (total + margin) / 2.0,
                "away_points": (total - margin) / 2.0,
            },
            index=features.index,
        )


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


def _relative_features(games: pd.DataFrame) -> pd.DataFrame:
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


def build_features(games: pd.DataFrame) -> pd.DataFrame:
    games = ensure_elo_columns(games)
    features = _relative_features(games)
    features["elo_diff"] = games["home_elo"] - games["away_elo"]
    return features[FEATURE_NAMES]


def build_score_features(games: pd.DataFrame) -> pd.DataFrame:
    features = _relative_features(games)
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


def _regression_pipeline(alpha: float) -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=alpha))])


def _fit_margin_model(features: pd.DataFrame, margin: pd.Series) -> MarginWinModel:
    pipeline = _regression_pipeline(MARGIN_RIDGE_ALPHA).fit(features[FEATURE_NAMES], margin)
    residual = margin.to_numpy() - pipeline.predict(features[FEATURE_NAMES])
    return MarginWinModel(pipeline, max(float(np.std(residual)), MIN_MARGIN_SIGMA))


def train_models(games: pd.DataFrame) -> ModelBundle:
    if len(games) < 50:
        raise ValueError("São necessários pelo menos 50 jogos para treinar o modelo.")

    ordered = games.sort_values("game_date").reset_index(drop=True)
    features = build_features(ordered)
    score_features = build_score_features(ordered)
    home_win = ordered["home_win"].astype(int)
    margin = ordered["home_points"] - ordered["away_points"]
    total = ordered["home_points"] + ordered["away_points"]
    split = temporal_split_index(ordered)

    evaluation_win = _fit_margin_model(features.iloc[:split], margin.iloc[:split])
    evaluation_total = _regression_pipeline(TOTAL_RIDGE_ALPHA).fit(
        score_features.iloc[:split], total.iloc[:split]
    )
    test_features = features.iloc[split:]
    probabilities = evaluation_win.predict_proba(test_features)[:, 1]
    test_margin = evaluation_win.predict_margin(test_features)
    test_total = evaluation_total.predict(score_features.iloc[split:])
    predicted_home = (test_total + test_margin) / 2.0
    predicted_away = (test_total - test_margin) / 2.0
    actual_home = ordered["home_points"].iloc[split:].to_numpy()
    actual_away = ordered["away_points"].iloc[split:].to_numpy()
    y_test = home_win.iloc[split:]

    metrics = {
        "score_model_version": float(SCORE_MODEL_VERSION),
        "score_feature_count": float(len(SCORE_FEATURE_NAMES)),
        "accuracy": float(accuracy_score(y_test, (probabilities >= 0.5).astype(int))),
        "log_loss": float(log_loss(y_test, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y_test, probabilities)),
        "home_points_mae": float(mean_absolute_error(actual_home, predicted_home)),
        "away_points_mae": float(mean_absolute_error(actual_away, predicted_away)),
        "margin_mae": float(mean_absolute_error(actual_home - actual_away, test_margin)),
        "margin_sigma": float(evaluation_win.sigma),
    }

    return ModelBundle(
        win_model=_fit_margin_model(features, margin),
        total_model=_regression_pipeline(TOTAL_RIDGE_ALPHA).fit(score_features, total),
        metrics=metrics,
        residual_std_home=max(float(np.std(actual_home - predicted_home)), 5.0),
        residual_std_away=max(float(np.std(actual_away - predicted_away)), 5.0),
    )


def _relative_matchup_features(
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


def matchup_features(
    home: dict[str, float],
    away: dict[str, float],
    home_rest_days: int,
    away_rest_days: int,
) -> pd.DataFrame:
    features = _relative_matchup_features(home, away, home_rest_days, away_rest_days)
    # `elo` vem de `data.team_snapshot`; sem ele os dois times contam como iguais.
    features["elo_diff"] = home.get("elo", ELO_BASE) - away.get("elo", ELO_BASE)
    return features[FEATURE_NAMES]


def _factor_contributions(model: MarginWinModel, features: pd.DataFrame) -> list[tuple[str, float]]:
    scaler: StandardScaler = model.pipeline.named_steps["scale"]
    ridge: Ridge = model.pipeline.named_steps["model"]
    scaled = scaler.transform(features[FEATURE_NAMES])[0]
    # Em unidades do argumento da curva normal: a soma é a margem em desvios-padrão.
    contributions = scaled * ridge.coef_ / model.sigma
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
    features = _relative_matchup_features(home, away, home_rest_days, away_rest_days)
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
    scores = bundle.predict_scores(features, score_features).iloc[0]
    predicted_home = float(scores["home_points"])
    predicted_away = float(scores["away_points"])

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
