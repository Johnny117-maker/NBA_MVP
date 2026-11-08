"""Pipelines, preparação das linhas e ajustes comuns (baseline da temporada, defesa, minutos)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import MIN_RESIDUAL_STD_MINUTES, MIN_RESIDUAL_STD_STAT, QUANTILE_ALPHAS


def _regression_pipeline() -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=2.0))])


def _direct_points_regressor() -> HistGradientBoostingRegressor:
    """Regressor não linear para pontos/minuto, leve e incluído no sklearn."""
    return HistGradientBoostingRegressor(
        max_iter=100,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=80,
        l2_regularization=2.0,
        random_state=0,
    )


def _quantile_pipeline(alpha: float) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                GradientBoostingRegressor(
                    loss="quantile",
                    alpha=alpha,
                    n_estimators=60,
                    max_depth=2,
                    min_samples_leaf=8,
                    random_state=0,
                ),
            ),
        ]
    )


def _fit_quantile_models(features: pd.DataFrame, target: pd.Series) -> dict:
    """Três `GradientBoostingRegressor` independentes (P10/P50/P90) sobre a
    mesma taxa-alvo. P50 é guardado só para inspeção — o intervalo usado na
    previsão vem de P10/P90 (ver `_predict_intervals`).
    """
    return {
        label: _quantile_pipeline(alpha).fit(features, target)
        for label, alpha in QUANTILE_ALPHAS.items()
    }


def _rate_features(stat: str) -> list:
    return [
        f"{stat}_per_min_avg3",
        f"{stat}_per_min_avg5",
        f"{stat}_per_min_avg10",
        f"{stat}_per_min_avg5_stint",
        f"{stat}_per_min_avg10_stint",
        "games_since_trade",
        "opponent_def_rating",
        "rest_days",
        "is_back_to_back",
        "is_long_rest",
        "is_home",
        f"prev_season_{stat}_avg",
        f"prev_season_{stat}_per_min",
        "prev_season_minutes_avg",
        "prev_season_games",
    ]


def _prepare(games: pd.DataFrame) -> pd.DataFrame:
    prepared = games.copy()
    season_defaults = {
        "prev_season_pts_avg": 9.0,
        "prev_season_reb_avg": 4.0,
        "prev_season_ast_avg": 2.0,
        "prev_season_minutes_avg": 18.0,
        "prev_season_pts_per_min": 0.50,
        "prev_season_reb_per_min": 0.22,
        "prev_season_ast_per_min": 0.11,
        "prev_season_games": 0.0,
    }
    for column, default in season_defaults.items():
        if column not in prepared.columns:
            prepared[column] = default
        else:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce").fillna(default)
    if "games_since_trade" not in prepared.columns:
        prepared["games_since_trade"] = 0.0
    prepared["games_since_trade"] = pd.to_numeric(
        prepared["games_since_trade"], errors="coerce"
    ).fillna(0.0).clip(lower=0.0)
    prepared["is_home"] = prepared["is_home"].fillna(False).astype(int)
    prepared["rest_days"] = pd.to_numeric(prepared["rest_days"], errors="coerce").fillna(3).clip(lower=0)
    prepared["is_back_to_back"] = (prepared["rest_days"] <= 1).astype(int)
    prepared["is_long_rest"] = (prepared["rest_days"] >= 4).astype(int)
    return prepared


def _season_baseline_weight(prepared: pd.DataFrame) -> np.ndarray:
    """Peso da média da temporada-base: maior no início de um stint novo.

    Parte de 60% no primeiro jogo do stint, diminui 4 p.p. por jogo e mantém
    pelo menos 20% da referência anual. O peso é reduzido pela confiabilidade
    do baseline quando há menos de 10 jogos históricos disponíveis.
    """
    games_since_trade = pd.to_numeric(
        prepared["games_since_trade"], errors="coerce"
    ).fillna(0.0).clip(lower=0.0).to_numpy()
    baseline_games = pd.to_numeric(
        prepared["prev_season_games"], errors="coerce"
    ).fillna(0.0).clip(lower=0.0).to_numpy()
    role_weight = np.clip(0.60 - 0.04 * games_since_trade, 0.20, 0.60)
    reliability = np.clip(baseline_games / 10.0, 0.0, 1.0)
    return role_weight * reliability


def _blend_season_baseline(
    stat: str,
    model_prediction: np.ndarray,
    predicted_minutes: np.ndarray,
    prepared: pd.DataFrame,
) -> np.ndarray:
    """Combina a previsão dinâmica com a média da temporada-base por minuto."""
    prediction = np.maximum(0.0, np.asarray(model_prediction, dtype=float))
    baseline_rate = pd.to_numeric(
        prepared[f"prev_season_{stat}_per_min"], errors="coerce"
    ).fillna(0.0).clip(lower=0.0).to_numpy()
    baseline_prediction = baseline_rate * np.maximum(0.0, np.asarray(predicted_minutes, dtype=float))
    weight = _season_baseline_weight(prepared)
    return np.maximum(0.0, (1.0 - weight) * prediction + weight * baseline_prediction)


def _opponent_defense_factor(
    prepared: pd.DataFrame,
    league_avg_opponent_def_rating: float,
) -> np.ndarray:
    """Ajuste moderado e interpretável de pontos pelo rating defensivo rival.

    O defensive rating representa pontos permitidos por 100 posses: valores
    mais altos indicam uma defesa mais permissiva, então a projeção de pontos
    sobe; valores mais baixos reduzem a projeção. A inclinação é deliberadamente
    conservadora (0,25% por ponto de rating) e limitada a +/-10%, evitando que
    uma estimativa extrema do adversário domine o modelo individual.

    Esta camada é um prior de contexto para partidas futuras, não uma relação
    causal estimada pelo teste atual. O backtest deve confirmar se ela melhora
    o erro em temporadas fora da amostra.
    """
    if "opponent_def_rating" not in prepared.columns:
        return np.ones(len(prepared), dtype=float)

    ratings = pd.to_numeric(prepared["opponent_def_rating"], errors="coerce")
    reference = float(league_avg_opponent_def_rating)
    if not np.isfinite(reference) or reference <= 0:
        return np.ones(len(prepared), dtype=float)

    ratings = ratings.fillna(reference).to_numpy(dtype=float)
    adjustment = 1.0 + 0.0025 * (ratings - reference)
    return np.clip(adjustment, 0.90, 1.10)


def _temporal_train_test_split(
    rows: pd.DataFrame, train_fraction: float = 0.8
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide por datas completas: partidas de um mesmo dia nunca se separam."""
    ordered = rows.sort_values("game_date").copy()
    date_key = pd.to_datetime(ordered["game_date"]).dt.normalize()
    unique_dates = np.sort(date_key.dropna().unique())
    if len(unique_dates) < 2:
        raise ValueError("São necessárias pelo menos duas datas distintas para avaliar o modelo.")
    split_index = min(max(int(len(unique_dates) * train_fraction), 1), len(unique_dates) - 1)
    cutoff = pd.Timestamp(unique_dates[split_index])
    train_rows = ordered.loc[date_key < cutoff]
    test_rows = ordered.loc[date_key >= cutoff]
    if train_rows.empty or test_rows.empty:
        raise ValueError("Não foi possível criar uma divisão temporal de treino e teste.")
    return train_rows, test_rows


def _fta_per_fga_ratio(fga_rate: pd.Series, fta_rate: pd.Series) -> pd.Series:
    """Proporção histórica FTA/FGA — uma razão, não um modelo (seção 4.2 do
    planejamento: "estimar tentativas de lance livre a partir do volume de
    arremessos de quadra")."""
    return (fta_rate / fga_rate.replace(0, np.nan)).fillna(0.0)


def _calibrate_minutes_predictions(
    model_minutes: np.ndarray | pd.Series, features: pd.DataFrame
) -> np.ndarray:
    """Combina o modelo de minutos com um prior de rotação observado até o jogo.

    Usa minutos recentes do stint atual, histórico recente geral e média da
    temporada anterior. O peso do stint cresce com a quantidade de jogos já
    disputados pelo jogador na passagem atual; em uma troca recente, reduz a
    confiança nas poucas observações do novo time.
    """
    frame = _prepare(features)
    model_values = np.maximum(0.0, np.asarray(model_minutes, dtype=float).reshape(-1))

    def values(column: str, default: float) -> np.ndarray:
        if column not in frame.columns:
            return np.full(len(frame), float(default))
        return (
            pd.to_numeric(frame[column], errors="coerce")
            .fillna(default)
            .clip(lower=0.0)
            .to_numpy(dtype=float)
        )

    stint_fast = values("minutes_avg5_stint", 18.0)
    stint_slow = values("minutes_avg10_stint", 18.0)
    career_fast = values("minutes_avg5", 18.0)
    career_slow = values("minutes_avg10", 18.0)
    season_minutes = values("prev_season_minutes_avg", 18.0)
    games_in_stint = values("games_since_trade", 0.0)

    stint_recent = 0.65 * stint_fast + 0.35 * stint_slow
    career_recent = 0.60 * career_fast + 0.40 * career_slow
    stint_support = np.clip(games_in_stint / 6.0, 0.0, 1.0)
    without_stint_history = 0.65 * career_recent + 0.35 * season_minutes
    history_prior = (
        stint_support * stint_recent + (1.0 - stint_support) * without_stint_history
    )

    # Evita que o contexto histórico anule o regressor; aumenta ligeiramente
    # seu peso conforme há mais jogos observados na rotação atual.
    history_weight = 0.25 + 0.10 * stint_support
    calibrated = (1.0 - history_weight) * model_values + history_weight * history_prior
    return np.maximum(0.0, calibrated)


def _prediction_confidence(
    residual_std: dict[str, float],
    predicted_minutes: float,
    stats: dict[str, float],
    context: dict | pd.Series,
) -> str:
    """Rótulo prudente baseado em erro histórico, suporte do histórico e stint.

    É uma classe heurística de incerteza relativa; não é probabilidade de acerto.
    O histórico de erro é aprendido exclusivamente nos dados de validação temporal.
    """
    def get_num(key: str, default: float = 0.0) -> float:
        try:
            value = float(context.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if np.isfinite(value) else default

    minutes = max(float(predicted_minutes), 0.0)
    minutes_ratio = (1.28 * residual_std.get("minutes", MIN_RESIDUAL_STD_MINUTES)) / max(minutes, 12.0)
    relative_errors = [
        1.28 * residual_std.get("pts", MIN_RESIDUAL_STD_STAT) / max(stats.get("pts", 0.0), 12.0),
        1.28 * residual_std.get("reb", MIN_RESIDUAL_STD_STAT) / max(stats.get("reb", 0.0), 4.0),
        1.28 * residual_std.get("ast", MIN_RESIDUAL_STD_STAT) / max(stats.get("ast", 0.0), 3.0),
    ]
    maximum_relative_error = max(relative_errors)
    historical_games = get_num("games", get_num("games_before", 0.0))
    stint_games = get_num("games_since_trade", 0.0)

    if (
        historical_games < 8
        or minutes < 10
        or minutes_ratio > 0.45
        or maximum_relative_error > 0.70
    ):
        return "Baixa"
    if (
        historical_games >= 20
        and stint_games >= 8
        and minutes_ratio <= 0.28
        and maximum_relative_error <= 0.42
    ):
        return "Alta"
    return "Média"
