"""Backtest walk-forward dos modelos de jogadores."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from .config import SIMPLE_RATE_STATS, PlayerModelBundle
from .prediction import _predict_intervals, predict_from_features
from .preparation import _prediction_confidence, _prepare
from .training import train_player_models


def _fold_boundaries(ordered: pd.DataFrame, n_folds: int, min_train_games: int):
    """Datas normalizadas, datas únicas e índices de data que separam os folds."""
    date_key = pd.to_datetime(ordered["game_date"]).dt.normalize()
    unique_dates = np.sort(date_key.dropna().unique())
    if len(unique_dates) < n_folds + 2:
        raise ValueError(
            f"São necessárias pelo menos {n_folds + 2} datas distintas para {n_folds} folds "
            "e um treino inicial com mais de uma data."
        )

    rows_per_date = date_key.value_counts().sort_index()
    cumulative_rows = rows_per_date.cumsum().to_numpy()
    first_test_date = int(np.searchsorted(cumulative_rows, min_train_games, side="left"))
    # O treinador também faz avaliação temporal interna; por isso o primeiro
    # fold precisa de ao menos duas datas para conseguir formar treino/teste.
    first_test_date = min(max(first_test_date, 2), len(unique_dates) - 1)
    boundaries = np.linspace(first_test_date, len(unique_dates), n_folds + 1, dtype=int)
    return date_key, unique_dates, boundaries


def _fold_prediction_records(
    fold_index: int, bundle: PlayerModelBundle, predicted: pd.DataFrame, test_fold_valid: pd.DataFrame
) -> list[dict]:
    """Uma linha por jogador-partida do fold, com previsto, realizado e erros."""
    records: list[dict] = []
    for row_index, actual_row in test_fold_valid.iterrows():
        predicted_row = predicted.loc[row_index]
        forecast_stats = {
            stat: float(predicted_row[stat]) for stat in ("pts", "reb", "ast")
        }
        confidence = _prediction_confidence(
            bundle.residual_std,
            float(predicted_row["minutes"]),
            forecast_stats,
            actual_row,
        )
        record = {
            "fold": fold_index + 1,
            "game_date": pd.Timestamp(actual_row["game_date"]).date().isoformat(),
            "game_id": actual_row.get("game_id"),
            "player_id": actual_row.get("player_id"),
            "player_name": actual_row.get("player_name"),
            "team": actual_row.get("team"),
            "opponent": actual_row.get("opponent"),
            "is_home": actual_row.get("is_home"),
            "confidence": confidence,
        }
        for stat in ("minutes", "pts", "reb", "ast"):
            record[f"predicted_{stat}"] = float(predicted_row[stat])
            record[f"actual_{stat}"] = float(actual_row[stat])
            record[f"{stat}_error"] = float(predicted_row[stat] - actual_row[stat])
            record[f"{stat}_absolute_error"] = abs(record[f"{stat}_error"])
        records.append(record)
    return records


def _fold_metrics(
    fold_index: int,
    train_fold: pd.DataFrame,
    test_fold_valid: pd.DataFrame,
    predicted: pd.DataFrame,
    intervals: dict,
    stats_to_evaluate: list[str],
) -> dict:
    """Erro médio, viés, referências e cobertura dos intervalos de um fold."""
    fold_metrics: dict[str, int | float] = {
        "fold": fold_index,
        "n_train": int(len(train_fold)),
        "n_test": int(len(test_fold_valid)),
    }
    for stat in stats_to_evaluate:
        fold_metrics[f"{stat}_mae"] = float(
            mean_absolute_error(test_fold_valid[stat], predicted[stat])
        )
        fold_metrics[f"{stat}_bias"] = float(
            (predicted[stat].to_numpy() - test_fold_valid[stat].to_numpy()).mean()
        )
    baseline_points = np.maximum(
        0.0,
        test_fold_valid["pts_per_min_avg5"].to_numpy() * predicted["minutes"].to_numpy(),
    )
    fold_metrics["pts_chain_mae"] = float(
        mean_absolute_error(test_fold_valid["pts"], predicted["pts_chain"])
    )
    fold_metrics["pts_baseline_mae"] = float(
        mean_absolute_error(test_fold_valid["pts"], baseline_points)
    )
    prepared_fold = _prepare(test_fold_valid)
    for stat in ("pts", *SIMPLE_RATE_STATS):
        seasonal_reference = (
            prepared_fold[f"prev_season_{stat}_per_min"].to_numpy()
            * predicted["minutes"].to_numpy()
        )
        fold_metrics[f"{stat}_season_baseline_mae"] = float(
            mean_absolute_error(test_fold_valid[stat], seasonal_reference)
        )
    for stat in ("pts", *SIMPLE_RATE_STATS):
        low, high = intervals[stat]
        inside = (test_fold_valid[stat] >= low) & (test_fold_valid[stat] <= high)
        fold_metrics[f"{stat}_interval_coverage"] = float(inside.mean())
    return fold_metrics


def _aggregate_folds(fold_results: list[dict], stats_to_evaluate: list[str]) -> dict:
    """Média das métricas de todos os folds."""
    aggregate = {
        f"{stat}_mae": float(np.mean([fold[f"{stat}_mae"] for fold in fold_results]))
        for stat in stats_to_evaluate
    }
    aggregate["pts_chain_mae"] = float(
        np.mean([fold["pts_chain_mae"] for fold in fold_results])
    )
    aggregate["pts_baseline_mae"] = float(
        np.mean([fold["pts_baseline_mae"] for fold in fold_results])
    )
    for stat in ("pts", *SIMPLE_RATE_STATS):
        aggregate[f"{stat}_season_baseline_mae"] = float(
            np.mean([fold[f"{stat}_season_baseline_mae"] for fold in fold_results])
        )
    for stat in ("pts", *SIMPLE_RATE_STATS):
        aggregate[f"{stat}_interval_coverage"] = float(
            np.mean([fold[f"{stat}_interval_coverage"] for fold in fold_results])
        )
    for stat in stats_to_evaluate:
        aggregate[f"{stat}_bias"] = float(
            np.mean([fold[f"{stat}_bias"] for fold in fold_results])
        )
    aggregate["n_folds"] = len(fold_results)
    return aggregate


def walk_forward_evaluate(
    games_with_features: pd.DataFrame,
    n_folds: int = 5,
    min_train_games: int = 200,
    interval_method: str = "normal",
) -> dict:
    """Backtest progressivo, agrupando por data para não dividir uma partida.

    ``min_train_games`` conserva o nome histórico do parâmetro, mas representa
    o número mínimo de linhas jogador-partida no conjunto inicial de treino.
    As fronteiras reais dos folds são datas completas, não linhas individuais.
    """
    ordered = _prepare(games_with_features).sort_values("game_date").reset_index(drop=True)
    if len(ordered) < min_train_games * 2:
        raise ValueError(
            f"São necessários pelo menos {min_train_games * 2} jogos para validação "
            "walk-forward."
        )

    date_key, unique_dates, boundaries = _fold_boundaries(ordered, n_folds, min_train_games)

    stats_to_evaluate = ["minutes", "pts", *SIMPLE_RATE_STATS]
    fold_results = []
    prediction_records: list[dict] = []

    for fold_index in range(n_folds):
        train_end_date = boundaries[fold_index]
        test_end_date = boundaries[fold_index + 1]
        if test_end_date <= train_end_date:
            continue

        train_cutoff = pd.Timestamp(unique_dates[train_end_date])
        test_cutoff = pd.Timestamp(unique_dates[test_end_date]) if test_end_date < len(unique_dates) else None
        train_fold = ordered.loc[date_key < train_cutoff]
        test_mask = date_key >= train_cutoff
        if test_cutoff is not None:
            test_mask &= date_key < test_cutoff
        test_fold = ordered.loc[test_mask]
        test_fold_valid = test_fold[test_fold["minutes"] > 0]
        if train_fold.empty or test_fold_valid.empty:
            continue

        bundle = train_player_models(train_fold, interval_method=interval_method)
        predicted = predict_from_features(bundle, test_fold_valid)
        intervals = _predict_intervals(bundle, test_fold_valid, predicted)
        prediction_records.extend(_fold_prediction_records(fold_index, bundle, predicted, test_fold_valid))
        fold_results.append(
            _fold_metrics(fold_index, train_fold, test_fold_valid, predicted, intervals, stats_to_evaluate)
        )

    if not fold_results:
        raise ValueError("Não foi possível formar nenhum fold de validação walk-forward.")

    aggregate = {
        f"{stat}_mae": float(np.mean([fold[f"{stat}_mae"] for fold in fold_results]))
        for stat in stats_to_evaluate
    }
    aggregate["pts_chain_mae"] = float(
        np.mean([fold["pts_chain_mae"] for fold in fold_results])
    )
    aggregate["pts_baseline_mae"] = float(
        np.mean([fold["pts_baseline_mae"] for fold in fold_results])
    )
    for stat in ("pts", *SIMPLE_RATE_STATS):
        aggregate[f"{stat}_season_baseline_mae"] = float(
            np.mean([fold[f"{stat}_season_baseline_mae"] for fold in fold_results])
        )
    for stat in ("pts", *SIMPLE_RATE_STATS):
        aggregate[f"{stat}_interval_coverage"] = float(
            np.mean([fold[f"{stat}_interval_coverage"] for fold in fold_results])
        )
    for stat in stats_to_evaluate:
        aggregate[f"{stat}_bias"] = float(
            np.mean([fold[f"{stat}_bias"] for fold in fold_results])
        )
    aggregate["n_folds"] = len(fold_results)

    aggregate = _aggregate_folds(fold_results, stats_to_evaluate)

    predictions_frame = pd.DataFrame(prediction_records)
    if not predictions_frame.empty:
        predictions_frame["game_date"] = pd.to_datetime(predictions_frame["game_date"])
        predictions_frame = predictions_frame.sort_values(
            ["game_date", "player_name"], na_position="last"
        ).reset_index(drop=True)

    return {
        "folds": fold_results,
        "aggregate": aggregate,
        "predictions": predictions_frame,
    }
