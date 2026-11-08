"""Backtest walk-forward do modelo de zonas."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from ..shot_features import ZONES
from .features import _share_features
from .prediction import expected_fg_points, predict_zone_distribution
from .splits import walk_forward_boundaries
from .training import train_zone_models


def walk_forward_evaluate_zone_models(
    zone_games_with_features: pd.DataFrame, n_folds: int = 5, min_train_games: int = 30
) -> dict:
    """Validação walk-forward dos modelos de zona (seção 17 do planejamento):
    treina até uma data, avalia no pedaço seguinte, avança — mesmo princípio
    de `player_model/evaluation.py::walk_forward_evaluate`.

    Usa o **FGA real** de cada jogo do teste (não uma previsão) para calcular
    `fg_points_mae`: isola o erro da decomposição por zona do erro do modelo
    de volume de arremessos, que já é validado separadamente em
    `player_model/`. Reporta também o MAE de participação (`share`) por
    zona, fold a fold.
    """
    ordered = zone_games_with_features.sort_values("game_date").reset_index(drop=True)
    if len(ordered) < min_train_games * 2:
        raise ValueError(
            f"São necessários pelo menos {min_train_games * 2} jogos (de qualquer "
            "jogador) para validação walk-forward dos modelos de zona."
        )

    boundaries = walk_forward_boundaries(ordered["game_date"], n_folds, min_train_games)
    fold_results = []

    for fold_index in range(n_folds):
        train_end = boundaries[fold_index]
        test_end = boundaries[fold_index + 1]
        if test_end <= train_end:
            continue
        train_fold = ordered.iloc[:train_end]
        test_fold = ordered.iloc[train_end:test_end]
        if test_fold.empty:
            continue

        bundle = train_zone_models(train_fold)
        zone_predictions = predict_zone_distribution(bundle, test_fold)
        predicted_points = expected_fg_points(zone_predictions, test_fold["total_fga"])

        fold_metrics = {
            "fold": fold_index,
            "n_train": int(train_end),
            "n_test": int(len(test_fold)),
            "fg_points_mae": float(
                mean_absolute_error(test_fold["total_fg_points"], predicted_points.reindex(test_fold.index))
            ),
        }
        for zone in ZONES:
            share_features = _share_features(zone)
            predicted_share = np.maximum(0.0, bundle.share_models[zone].predict(test_fold[share_features]))
            fold_metrics[f"share_mae_{zone}"] = float(
                mean_absolute_error(test_fold[f"share_{zone}"], predicted_share)
            )
        fold_results.append(fold_metrics)

    if not fold_results:
        raise ValueError("Não foi possível formar nenhum fold de validação walk-forward.")

    aggregate = {"fg_points_mae": float(np.mean([fold["fg_points_mae"] for fold in fold_results]))}
    for zone in ZONES:
        aggregate[f"share_mae_{zone}"] = float(
            np.mean([fold[f"share_mae_{zone}"] for fold in fold_results])
        )
    aggregate["n_folds"] = len(fold_results)
    return {"folds": fold_results, "aggregate": aggregate}
