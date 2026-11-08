"""Projeção de jogos (valores centrais, intervalos e probabilidades de linhas)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import (
    EFFICIENCY_FEATURES,
    MINUTES_FEATURES,
    PTS_DIRECT_FEATURES,
    PTS_QUANTILE_FEATURES,
    SIMPLE_RATE_STATS,
    VOLUME_FEATURES,
    PlayerGamePrediction,
    PlayerModelBundle,
)
from .preparation import (
    _blend_season_baseline,
    _calibrate_minutes_predictions,
    _fta_per_fga_ratio,
    _opponent_defense_factor,
    _prediction_confidence,
    _prepare,
    _rate_features,
)


def predict_from_features(bundle: PlayerModelBundle, rows: pd.DataFrame) -> pd.DataFrame:
    """Previsão em lote (minutos, pontos, rebotes, assistências) a partir de
    linhas de features já calculadas.

    Função de baixo nível compartilhada por `predict_player_game` (que monta
    uma linha a partir do snapshot ao vivo) e por `walk_forward_evaluate`
    (que aplica direto às linhas de treino/avaliação já existentes). Retorna a
    previsão direta principal e também `pts_chain` para comparar a alternativa
    de volume × eficiência.
    """
    prepared = _prepare(rows)

    raw_minutes = bundle.minutes_model.predict(prepared[MINUTES_FEATURES])
    predicted_minutes = _calibrate_minutes_predictions(raw_minutes, prepared)

    predicted_fga_rate = np.maximum(0.0, bundle.fga_model.predict(prepared[VOLUME_FEATURES]))
    predicted_fga = predicted_fga_rate * predicted_minutes

    predicted_ts_pct = np.clip(bundle.ts_pct_model.predict(prepared[EFFICIENCY_FEATURES]), 0.0, None)

    fta_ratio = _fta_per_fga_ratio(
        prepared["fga_per_min_avg10"], prepared["fta_per_min_avg10"]
    ).to_numpy()
    predicted_fta = predicted_fga * fta_ratio
    predicted_pts_chain = np.maximum(
        0.0, predicted_ts_pct * 2 * (predicted_fga + 0.44 * predicted_fta)
    )
    if bundle.direct_pts_model is not None:
        predicted_pts_rate = np.maximum(
            0.0, bundle.direct_pts_model.predict(prepared[PTS_DIRECT_FEATURES])
        )
        predicted_pts_raw = predicted_pts_rate * predicted_minutes
        predicted_pts = _blend_season_baseline(
            "pts", predicted_pts_raw, predicted_minutes, prepared
        )
    else:
        # Compatibilidade com bundles antigos e objetos falsos usados em testes.
        predicted_pts = predicted_pts_chain

    opponent_factor = _opponent_defense_factor(
        prepared, bundle.league_avg_opponent_def_rating
    )
    predicted_pts = np.maximum(0.0, predicted_pts * opponent_factor)
    predicted_pts_chain = np.maximum(0.0, predicted_pts_chain * opponent_factor)

    result = pd.DataFrame(
        {
            "minutes": predicted_minutes,
            "fga": predicted_fga,
            "ts_pct": predicted_ts_pct,
            "pts": predicted_pts,
            "pts_chain": predicted_pts_chain,
        },
        index=prepared.index,
    )
    for stat in SIMPLE_RATE_STATS:
        rate = bundle.rate_models[stat].predict(prepared[_rate_features(stat)])
        raw_stat = np.maximum(0.0, rate * predicted_minutes)
        result[stat] = _blend_season_baseline(stat, raw_stat, predicted_minutes, prepared)
    return result


def _predict_intervals(
    bundle: PlayerModelBundle, rows: pd.DataFrame, predicted: pd.DataFrame
) -> dict:
    """Intervalo (baixo, alto) por estatística (pts, reb, ast) — em lote,
    alinhado ao índice de `rows`/`predicted`.

    Normal(0, erro histórico) por padrão, ou os modelos de quantil (P10/P90)
    quando `bundle.interval_method == "quantile"`. Nesse segundo caso, o
    resultado passa por um `min`/`max`: três modelos de quantil treinados de
    forma independente não têm garantia de não se cruzar (o P10 previsto
    podendo sair maior que o P90 previsto para a mesma linha é um problema
    conhecido dessa técnica) — sem essa proteção, um intervalo cruzado
    quebraria a suposição de `low <= high` usada no resto do código.
    """
    prepared = _prepare(rows)
    minutes = predicted["minutes"].to_numpy()

    intervals = {}
    for stat in ("pts", *SIMPLE_RATE_STATS):
        if bundle.interval_method == "quantile" and bundle.quantile_rate_models is not None:
            features = PTS_QUANTILE_FEATURES if stat == "pts" else _rate_features(stat)
            p10_rate = bundle.quantile_rate_models[stat]["p10"].predict(prepared[features])
            p90_rate = bundle.quantile_rate_models[stat]["p90"].predict(prepared[features])
            p10_raw = np.maximum(0.0, p10_rate * minutes)
            p90_raw = np.maximum(0.0, p90_rate * minutes)
            p10_value = _blend_season_baseline(stat, p10_raw, minutes, prepared)
            p90_value = _blend_season_baseline(stat, p90_raw, minutes, prepared)
            if stat == "pts":
                opponent_factor = _opponent_defense_factor(
                    prepared, bundle.league_avg_opponent_def_rating
                )
                p10_value = p10_value * opponent_factor
                p90_value = p90_value * opponent_factor
            low = np.minimum(p10_value, p90_value)
            high = np.maximum(p10_value, p90_value)
        else:
            margin = 1.28 * bundle.residual_std[stat]
            low = np.maximum(0.0, predicted[stat].to_numpy() - margin)
            high = predicted[stat].to_numpy() + margin
        intervals[stat] = (
            pd.Series(low, index=rows.index),
            pd.Series(high, index=rows.index),
        )
    return intervals


def predict_player_game(
    bundle: PlayerModelBundle,
    snapshot: dict,
    is_home: bool = True,
    rest_days: int = 2,
    opponent_def_rating: float | None = None,
) -> PlayerGamePrediction:
    if opponent_def_rating is None:
        opponent_def_rating = bundle.league_avg_opponent_def_rating

    row = pd.DataFrame(
        [
            {
                "minutes_avg5": snapshot["minutes_avg5"],
                "minutes_avg10": snapshot["minutes_avg10"],
                "minutes_avg5_stint": snapshot["minutes_avg5_stint"],
                "minutes_avg10_stint": snapshot["minutes_avg10_stint"],
                "starter_rate_avg10": snapshot["starter_rate_avg10"],
                "starter_rate_avg10_stint": snapshot["starter_rate_avg10_stint"],
                "fga_per_min_avg3": snapshot["fga_per_min_avg3"],
                "fga_per_min_avg5": snapshot["fga_per_min_avg5"],
                "fga_per_min_avg10": snapshot["fga_per_min_avg10"],
                "fga_per_min_avg5_stint": snapshot["fga_per_min_avg5_stint"],
                "fga_per_min_avg10_stint": snapshot["fga_per_min_avg10_stint"],
                "fta_per_min_avg3": snapshot["fta_per_min_avg3"],
                "fta_per_min_avg5": snapshot["fta_per_min_avg5"],
                "fta_per_min_avg10": snapshot["fta_per_min_avg10"],
                "ts_pct_avg3": snapshot["ts_pct_avg3"],
                "ts_pct_avg5": snapshot["ts_pct_avg5"],
                "ts_pct_avg10": snapshot["ts_pct_avg10"],
                "ts_pct_avg3_stint": snapshot["ts_pct_avg3_stint"],
                "ts_pct_avg5_stint": snapshot["ts_pct_avg5_stint"],
                "ts_pct_avg10_stint": snapshot["ts_pct_avg10_stint"],
                "pts_per_min_avg3": snapshot["pts_per_min_avg3"],
                "pts_per_min_avg5": snapshot["pts_per_min_avg5"],
                "pts_per_min_avg10": snapshot["pts_per_min_avg10"],
                "pts_per_min_avg5_stint": snapshot["pts_per_min_avg5_stint"],
                "usg_pct_avg5": snapshot["usg_pct_avg5"],
                "usg_pct_avg10": snapshot["usg_pct_avg10"],
                "usg_pct_avg5_stint": snapshot["usg_pct_avg5_stint"],
                "usg_pct_avg10_stint": snapshot["usg_pct_avg10_stint"],
                "reb_per_min_avg3": snapshot["reb_per_min_avg3"],
                "reb_per_min_avg5": snapshot["reb_per_min_avg5"],
                "reb_per_min_avg10": snapshot["reb_per_min_avg10"],
                "reb_per_min_avg5_stint": snapshot["reb_per_min_avg5_stint"],
                "reb_per_min_avg10_stint": snapshot["reb_per_min_avg10_stint"],
                "ast_per_min_avg3": snapshot["ast_per_min_avg3"],
                "ast_per_min_avg5": snapshot["ast_per_min_avg5"],
                "ast_per_min_avg10": snapshot["ast_per_min_avg10"],
                "ast_per_min_avg5_stint": snapshot["ast_per_min_avg5_stint"],
                "ast_per_min_avg10_stint": snapshot["ast_per_min_avg10_stint"],
                "games_since_trade": snapshot["games_since_trade"],
                "opponent_def_rating": opponent_def_rating,
                "rest_days": rest_days,
                "is_home": int(is_home),
                "prev_season_pts_avg": snapshot.get("prev_season_pts_avg", 9.0),
                "prev_season_reb_avg": snapshot.get("prev_season_reb_avg", 4.0),
                "prev_season_ast_avg": snapshot.get("prev_season_ast_avg", 2.0),
                "prev_season_minutes_avg": snapshot.get("prev_season_minutes_avg", 18.0),
                "prev_season_pts_per_min": snapshot.get("prev_season_pts_per_min", 0.50),
                "prev_season_reb_per_min": snapshot.get("prev_season_reb_per_min", 0.22),
                "prev_season_ast_per_min": snapshot.get("prev_season_ast_per_min", 0.11),
                "prev_season_games": snapshot.get("prev_season_games", 0.0),
            }
        ]
    )
    predicted = predict_from_features(bundle, row)
    predicted_row = predicted.iloc[0]
    predicted_minutes = float(predicted_row["minutes"])

    intervals = _predict_intervals(bundle, row, predicted)
    stats, stats_low, stats_high = {}, {}, {}
    for stat in ("pts", *SIMPLE_RATE_STATS):
        low_series, high_series = intervals[stat]
        stats[stat] = float(predicted_row[stat])
        stats_low[stat] = float(low_series.iloc[0])
        stats_high[stat] = float(high_series.iloc[0])

    confidence = _prediction_confidence(
        bundle.residual_std,
        predicted_minutes,
        stats,
        {**snapshot, "games": snapshot.get("games", 0.0)},
    )

    return PlayerGamePrediction(
        minutes=predicted_minutes,
        stats=stats,
        stats_low=stats_low,
        stats_high=stats_high,
        confidence=confidence,
        projected_fga=float(predicted_row["fga"]),
        projected_ts_pct=float(predicted_row["ts_pct"]),
        chain_pts=float(predicted_row["pts_chain"]),
    )


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


def over_probability(predicted_value: float, residual_std: float, line: float) -> float:
    """Probabilidade de a estatística real superar `line`, aproximando o erro
    do modelo por uma Normal(0, `residual_std`) em torno da previsão.

    É uma leitura estatística do próprio modelo (quão longe `line` está da
    previsão, em unidades do erro histórico), não uma odds de mercado nem
    orientação de aposta — o projeto não usa odds (ver README).
    """
    if residual_std <= 0:
        return 1.0 if predicted_value > line else 0.0
    z = (line - predicted_value) / residual_std
    return 1.0 - _normal_cdf(z)


def _bucket_cdf(predicted_value: float, residual_std: float, cut: float) -> float:
    if cut == -math.inf:
        return 0.0
    if cut == math.inf:
        return 1.0
    if residual_std <= 0:
        return 1.0 if predicted_value <= cut else 0.0
    return _normal_cdf((cut - predicted_value) / residual_std)


def range_probabilities(
    predicted_value: float, residual_std: float, n_buckets: int = 5
) -> list:
    """Probabilidade de a estatística real cair em cada uma de `n_buckets`
    faixas centradas na previsão (seção 8 do documento de faixas de
    desempenho: "até 19 / 20–24 / 25–29 / 30–34 / 35 ou mais").

    Largura de cada faixa = `residual_std` arredondado (mínimo 1) — quanto
    mais incerto o modelo, mais largas as faixas, em vez de um valor fixo que
    não faria sentido para pontos, rebotes e assistências ao mesmo tempo, nem
    para um astro e um jogador de banco. Mesma aproximação normal de
    `over_probability`, fatiada em vários pontos de corte em vez de um só.
    """
    if n_buckets < 2:
        raise ValueError("n_buckets precisa ser pelo menos 2.")

    width = max(round(residual_std), 1)
    center = round(predicted_value)
    half = n_buckets / 2
    cuts = [center + (i - half) * width for i in range(1, n_buckets)]
    boundaries = [-math.inf, *cuts, math.inf]

    buckets = []
    for low, high in zip(boundaries[:-1], boundaries[1:], strict=True):
        probability = _bucket_cdf(predicted_value, residual_std, high) - _bucket_cdf(
            predicted_value, residual_std, low
        )
        if low == -math.inf:
            label = f"≤ {math.floor(high)}"
        elif high == math.inf:
            label = f"≥ {math.floor(low) + 1}"
        else:
            label = f"{math.floor(low) + 1}–{math.floor(high)}"
        buckets.append(
            {"label": label, "low": low, "high": high, "probability": max(0.0, probability)}
        )
    return buckets
