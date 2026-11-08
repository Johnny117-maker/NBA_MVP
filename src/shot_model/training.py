"""Treino do modelo de zonas (participação e eficiência por zona)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline

from ..shot_features import ZONES
from .config import (
    MIN_GAMES_FOR_EFFICIENCY_MODEL,
    MIN_RESIDUAL_STD_FG_PCT,
    MIN_RESIDUAL_STD_SHARE,
    ZoneModelBundle,
)
from .features import _efficiency_features, _regression_pipeline, _share_features
from .splits import split_zone_games_by_date


def train_zone_models(zone_games_with_features: pd.DataFrame) -> ZoneModelBundle:
    """Treina os modelos de zona: um Ridge de participação (`share`) e um Ridge
    de eficiência (`fg_pct`) por zona, igual em espírito aos modelos de
    `player_model/` (regressão sobre a taxa agregada, não classificação por
    arremesso individual — mesma escolha já feita para TS%/per-36 no resto do
    projeto). Um único treino usa os jogos de **todos** os jogadores já
    coletados (não um modelo por jogador) — mesma arquitetura de
    `train_player_models`, generaliza melhor conforme mais jogadores entram
    na base.
    """
    if len(zone_games_with_features) < 30:
        raise ValueError(
            "São necessários pelo menos 30 jogos (de qualquer jogador) para treinar "
            "os modelos de zona."
        )

    ordered = zone_games_with_features.sort_values("game_date").reset_index(drop=True)
    train_rows, test_rows = split_zone_games_by_date(ordered)

    share_models_eval: dict[str, Pipeline] = {}
    fg_pct_models_eval: dict[str, Pipeline | None] = {}
    metrics: dict[str, float] = {}
    residual_std_share: dict[str, float] = {}
    residual_std_fg_pct: dict[str, float] = {}

    for zone in ZONES:
        share_features = _share_features(zone)
        share_model = _regression_pipeline().fit(train_rows[share_features], train_rows[f"share_{zone}"])
        predicted_share = np.maximum(0.0, share_model.predict(test_rows[share_features]))
        metrics[f"share_mae_{zone}"] = float(
            mean_absolute_error(test_rows[f"share_{zone}"], predicted_share)
        )
        residual_std_share[zone] = max(
            float(np.std(test_rows[f"share_{zone}"].to_numpy() - predicted_share)),
            MIN_RESIDUAL_STD_SHARE,
        )
        share_models_eval[zone] = share_model

        eff_features = _efficiency_features(zone)
        train_eff = train_rows[train_rows[f"attempts_{zone}"] > 0]
        test_eff = test_rows[test_rows[f"attempts_{zone}"] > 0]
        if len(train_eff) >= MIN_GAMES_FOR_EFFICIENCY_MODEL and len(test_eff) >= 5:
            fg_pct_model = _regression_pipeline().fit(train_eff[eff_features], train_eff[f"fg_pct_{zone}"])
            predicted_fg_pct = np.clip(fg_pct_model.predict(test_eff[eff_features]), 0.0, 1.0)
            metrics[f"fg_pct_mae_{zone}"] = float(
                mean_absolute_error(test_eff[f"fg_pct_{zone}"], predicted_fg_pct)
            )
            residual_std_fg_pct[zone] = max(
                float(np.std(test_eff[f"fg_pct_{zone}"].to_numpy() - predicted_fg_pct)),
                MIN_RESIDUAL_STD_FG_PCT,
            )
            fg_pct_models_eval[zone] = fg_pct_model
        else:
            fg_pct_models_eval[zone] = None
            residual_std_fg_pct[zone] = MIN_RESIDUAL_STD_FG_PCT

    league_avg_share = {zone: float(ordered[f"share_{zone}"].mean()) for zone in ZONES}
    league_avg_fg_pct = {}
    for zone in ZONES:
        qualified = ordered[ordered[f"attempts_{zone}"] > 0]
        league_avg_fg_pct[zone] = float(qualified[f"fg_pct_{zone}"].mean()) if not qualified.empty else 0.0

    final_share_models = {
        zone: clone(share_models_eval[zone]).fit(ordered[_share_features(zone)], ordered[f"share_{zone}"])
        for zone in ZONES
    }
    final_fg_pct_models: dict[str, Pipeline | None] = {}
    for zone in ZONES:
        all_eff = ordered[ordered[f"attempts_{zone}"] > 0]
        if fg_pct_models_eval[zone] is not None and len(all_eff) >= MIN_GAMES_FOR_EFFICIENCY_MODEL:
            final_fg_pct_models[zone] = clone(fg_pct_models_eval[zone]).fit(
                all_eff[_efficiency_features(zone)], all_eff[f"fg_pct_{zone}"]
            )
        else:
            final_fg_pct_models[zone] = None

    return ZoneModelBundle(
        share_models=final_share_models,
        fg_pct_models=final_fg_pct_models,
        metrics=metrics,
        residual_std_share=residual_std_share,
        residual_std_fg_pct=residual_std_fg_pct,
        league_avg_share=league_avg_share,
        league_avg_fg_pct=league_avg_fg_pct,
    )
