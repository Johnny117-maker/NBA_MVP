"""Treino e avaliação interna dos modelos de minutos, pontos, rebotes e assistências."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error

from .config import (
    EFFICIENCY_FEATURES,
    MIN_RESIDUAL_STD_MINUTES,
    MIN_RESIDUAL_STD_STAT,
    MINUTES_FEATURES,
    PTS_DIRECT_FEATURES,
    PTS_QUANTILE_FEATURES,
    SIMPLE_RATE_STATS,
    VOLUME_FEATURES,
    PlayerModelBundle,
)
from .preparation import (
    _blend_season_baseline,
    _calibrate_minutes_predictions,
    _direct_points_regressor,
    _fit_quantile_models,
    _fta_per_fga_ratio,
    _opponent_defense_factor,
    _prepare,
    _rate_features,
    _regression_pipeline,
    _temporal_train_test_split,
)


def _evaluate_minutes(train_rows: pd.DataFrame, test_rows: pd.DataFrame):
    """Treina e avalia o modelo de minutos; devolve (modelo, minutos previstos, métricas, desvios)."""
    minutes_eval = _regression_pipeline().fit(train_rows[MINUTES_FEATURES], train_rows["minutes"])
    predicted_minutes_raw = minutes_eval.predict(test_rows[MINUTES_FEATURES])
    predicted_minutes = _calibrate_minutes_predictions(
        predicted_minutes_raw, _prepare(test_rows)
    )

    metrics = {"minutes_mae": float(mean_absolute_error(test_rows["minutes"], predicted_minutes))}
    residual_std = {
        "minutes": max(
            float(np.std(test_rows["minutes"].to_numpy() - predicted_minutes)),
            MIN_RESIDUAL_STD_MINUTES,
        )
    }
    return minutes_eval, predicted_minutes, metrics, residual_std

def _evaluate_points(
    train_rows: pd.DataFrame,
    train_valid: pd.DataFrame,
    test_valid: pd.DataFrame,
    test_predicted_minutes: np.ndarray,
    metrics: dict,
    residual_std: dict,
):
    """Avalia os modelos de pontos (volume, eficiência e regressor direto); atualiza métricas e desvios.

    Devolve (modelo de FGA, modelo de TS%, regressor direto de pontos por minuto).
    """
    # TS% não existe (fica NaN) só em jogos sem nenhuma tentativa de
    # arremesso ou lance livre — não há nada a aprender sobre eficiência
    # nesses jogos, então o AJUSTE dos modelos de volume/eficiência usa só
    # as linhas com TS% válido. A AVALIAÇÃO (MAE, intervalo de erro), porém,
    # usa a mesma população de minutos > 0 dos outros modelos — senão o
    # número não seria comparável ao MAE de minutos/rebotes/assistências,
    # nem ao MAE do modelo de taxa única de antes desta versão.
    train_pts_valid = train_valid[train_valid["true_shooting_pct"].notna()]
    # Volume: FGA por minuto.
    fga_eval = _regression_pipeline().fit(
        train_pts_valid[VOLUME_FEATURES], train_pts_valid["fga"] / train_pts_valid["minutes"]
    )
    predicted_fga_rate = fga_eval.predict(test_valid[VOLUME_FEATURES])
    predicted_fga = np.maximum(0.0, predicted_fga_rate * test_predicted_minutes)

    # Eficiência: TS% (já usa o contexto do adversário).
    ts_pct_eval = _regression_pipeline().fit(
        train_pts_valid[EFFICIENCY_FEATURES], train_pts_valid["true_shooting_pct"]
    )
    predicted_ts_pct = np.clip(ts_pct_eval.predict(test_valid[EFFICIENCY_FEATURES]), 0.0, None)

    # FTA: proporção histórica FTA/FGA do próprio jogador, não um modelo.
    fta_ratio = _fta_per_fga_ratio(test_valid["fga_per_min_avg10"], test_valid["fta_per_min_avg10"])
    predicted_fta = predicted_fga * fta_ratio.to_numpy()

    # Referência interpretável por decomposição: FGA previsto × TS% × FTA/FGA.
    predicted_pts_chain = np.maximum(
        0.0, predicted_ts_pct * 2 * (predicted_fga + 0.44 * predicted_fta)
    )

    # Regressor direto de pontos/minuto. A projeção usa minutos previstos,
    # nunca os minutos reais da partida de teste.
    direct_pts_eval = _direct_points_regressor().fit(
        train_valid[PTS_DIRECT_FEATURES], train_valid["pts"] / train_valid["minutes"]
    )
    predicted_pts_rate = np.maximum(0.0, direct_pts_eval.predict(test_valid[PTS_DIRECT_FEATURES]))
    predicted_pts_unblended = predicted_pts_rate * test_predicted_minutes
    prepared_test_points = _prepare(test_valid)
    predicted_pts = _blend_season_baseline(
        "pts", predicted_pts_unblended, test_predicted_minutes, prepared_test_points
    )
    # O ajuste do adversário usa apenas o nível médio de defesa observado no
    # conjunto de treino, mantendo a mesma lógica da previsão para o próximo jogo.
    training_defense_reference = float(
        pd.to_numeric(train_rows["opponent_def_rating"], errors="coerce").mean()
    )
    defense_factor = _opponent_defense_factor(prepared_test_points, training_defense_reference)
    predicted_pts = predicted_pts * defense_factor
    predicted_pts_chain = predicted_pts_chain * defense_factor

    metrics["pts_mae"] = float(mean_absolute_error(test_valid["pts"], predicted_pts))
    season_baseline_pts = (
        _prepare(test_valid)["prev_season_pts_per_min"].to_numpy() * test_predicted_minutes
    )
    metrics["pts_season_baseline_mae"] = float(
        mean_absolute_error(test_valid["pts"], season_baseline_pts)
    )
    metrics["pts_direct_mae"] = metrics["pts_mae"]
    metrics["pts_chain_mae"] = float(
        mean_absolute_error(test_valid["pts"], predicted_pts_chain)
    )
    # Referência simples: taxa recente × minutos previstos.
    baseline_points = np.maximum(
        0.0, test_valid["pts_per_min_avg5"].to_numpy() * test_predicted_minutes
    )
    metrics["pts_baseline_mae"] = float(mean_absolute_error(test_valid["pts"], baseline_points))
    residual_std["pts"] = max(
        float(np.std(test_valid["pts"].to_numpy() - predicted_pts)), MIN_RESIDUAL_STD_STAT
    )
    return fga_eval, ts_pct_eval, direct_pts_eval

def _evaluate_rate_stats(
    train_valid: pd.DataFrame,
    test_valid: pd.DataFrame,
    test_predicted_minutes: np.ndarray,
    metrics: dict,
    residual_std: dict,
) -> dict:
    """Avalia rebotes e assistências (taxa por minuto); atualiza métricas e desvios."""
    rate_models_eval = {}
    for stat in SIMPLE_RATE_STATS:
        features = _rate_features(stat)
        model = _regression_pipeline().fit(
            train_valid[features], train_valid[stat] / train_valid["minutes"]
        )
        predicted_rate = model.predict(test_valid[features])
        predicted_stat_unblended = np.maximum(0.0, predicted_rate * test_predicted_minutes)
        prepared_test = _prepare(test_valid)
        predicted_stat = _blend_season_baseline(
            stat, predicted_stat_unblended, test_predicted_minutes, prepared_test
        )

        metrics[f"{stat}_mae"] = float(mean_absolute_error(test_valid[stat], predicted_stat))
        season_baseline = (
            prepared_test[f"prev_season_{stat}_per_min"].to_numpy() * test_predicted_minutes
        )
        metrics[f"{stat}_season_baseline_mae"] = float(
            mean_absolute_error(test_valid[stat], season_baseline)
        )
        residual_std[stat] = max(
            float(np.std(test_valid[stat].to_numpy() - predicted_stat)), MIN_RESIDUAL_STD_STAT
        )
        rate_models_eval[stat] = model
    return rate_models_eval

def _fit_final_models(
    ordered: pd.DataFrame, interval_method: str, minutes_eval, fga_eval, ts_pct_eval, rate_models_eval: dict
) -> dict:
    """Reajusta todos os modelos com a base inteira, depois da avaliação."""
    all_valid = ordered[ordered["minutes"] > 0]
    all_pts_valid = all_valid[all_valid["true_shooting_pct"].notna()]

    final_quantile_rate_models = None
    if interval_method == "quantile":
        final_quantile_rate_models = {
            "pts": _fit_quantile_models(
                all_valid[PTS_QUANTILE_FEATURES],
                all_valid["pts"] / all_valid["minutes"],
            )
        }
        for stat in SIMPLE_RATE_STATS:
            features = _rate_features(stat)
            final_quantile_rate_models[stat] = _fit_quantile_models(
                all_valid[features], all_valid[stat] / all_valid["minutes"]
            )

    final_minutes_model = clone(minutes_eval).fit(ordered[MINUTES_FEATURES], ordered["minutes"])
    final_fga_model = clone(fga_eval).fit(
        all_pts_valid[VOLUME_FEATURES], all_pts_valid["fga"] / all_pts_valid["minutes"]
    )
    final_ts_pct_model = clone(ts_pct_eval).fit(
        all_pts_valid[EFFICIENCY_FEATURES], all_pts_valid["true_shooting_pct"]
    )
    final_direct_pts_model = _direct_points_regressor().fit(
        all_valid[PTS_DIRECT_FEATURES], all_valid["pts"] / all_valid["minutes"]
    )
    final_rate_models = {
        stat: clone(rate_models_eval[stat]).fit(
            all_valid[_rate_features(stat)], all_valid[stat] / all_valid["minutes"]
        )
        for stat in SIMPLE_RATE_STATS
    }
    return dict(
        minutes_model=final_minutes_model,
        fga_model=final_fga_model,
        ts_pct_model=final_ts_pct_model,
        rate_models=final_rate_models,
        direct_pts_model=final_direct_pts_model,
        quantile_rate_models=final_quantile_rate_models,
    )


def train_player_models(
    games_with_rolling_features: pd.DataFrame, interval_method: str = "normal"
) -> PlayerModelBundle:
    """Treina os modelos de projeção de jogador.

    A estimativa final de pontos, rebotes e assistências combina o modelo
    dinâmico com a taxa por minuto da temporada-base, com maior peso nessa
    referência no início de uma nova passagem por um time.

    `interval_method="normal"` (padrão): intervalos de pts/reb/ast vêm de
    Normal(0, erro histórico) em torno da previsão central — rápido. A previsão
    central de pontos usa um regressor direto regularizado de pontos/minuto;
    a cadeia FGA × TS% é mantida como métrica de comparação. `interval_method="quantile"`: além dos
    modelos de sempre, treina modelos de quantil (P10/P90) por estatística
    para gerar intervalos assimétricos — mais caro (`GradientBoostingRegressor`
    em vez de Ridge, 3 modelos por estatística), pensado para comparar contra
    o modo normal via `walk_forward_evaluate` antes de virar padrão.
    """
    if interval_method not in ("normal", "quantile"):
        raise ValueError(f"interval_method inválido: {interval_method!r}")
    if len(games_with_rolling_features) < 50:
        raise ValueError("São necessários pelo menos 50 jogos para treinar o modelo.")

    ordered = _prepare(games_with_rolling_features).sort_values("game_date").reset_index(drop=True)
    train_rows, test_rows = _temporal_train_test_split(ordered, train_fraction=0.8)

    minutes_eval, predicted_minutes, metrics, residual_std = _evaluate_minutes(train_rows, test_rows)
    predicted_minutes_by_index = pd.Series(predicted_minutes, index=test_rows.index)
    train_valid = train_rows[train_rows["minutes"] > 0]
    test_valid = test_rows[test_rows["minutes"] > 0]
    test_predicted_minutes = predicted_minutes_by_index.loc[test_valid.index].to_numpy()

    fga_eval, ts_pct_eval, _direct_pts_eval = _evaluate_points(
        train_rows, train_valid, test_valid, test_predicted_minutes, metrics, residual_std
    )
    rate_models_eval = _evaluate_rate_stats(
        train_valid, test_valid, test_predicted_minutes, metrics, residual_std
    )
    final = _fit_final_models(ordered, interval_method, minutes_eval, fga_eval, ts_pct_eval, rate_models_eval)

    return PlayerModelBundle(
        minutes_model=final["minutes_model"],
        fga_model=final["fga_model"],
        ts_pct_model=final["ts_pct_model"],
        rate_models=final["rate_models"],
        metrics=metrics,
        residual_std=residual_std,
        league_avg_opponent_def_rating=float(ordered["opponent_def_rating"].mean()),
        direct_pts_model=final["direct_pts_model"],
        interval_method=interval_method,
        quantile_rate_models=final["quantile_rate_models"],
    )
