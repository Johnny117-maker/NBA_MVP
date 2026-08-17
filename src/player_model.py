from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MINUTES_FEATURES = [
    "minutes_avg5",
    "minutes_avg10",
    "minutes_avg5_stint",
    "minutes_avg10_stint",
    "starter_rate_avg10",
    "starter_rate_avg10_stint",
    "games_since_trade",
    "rest_days",
    "is_home",
]

# Pontos são decompostos em volume (quantos arremessos o jogador vai tentar)
# × eficiência (quão bem ele costuma converter), em vez de uma única taxa de
# "pontos por minuto" — separa "jogou mais e arremessou mais" de "arremessou
# igual, mas acertou mais", que reagem de forma diferente ao adversário.
VOLUME_FEATURES = [
    "fga_per_min_avg10",
    "fga_per_min_avg10_stint",
    "usg_pct_avg10",
    "usg_pct_avg10_stint",
    "games_since_trade",
    "rest_days",
    "is_home",
]
EFFICIENCY_FEATURES = [
    "ts_pct_avg10",
    "ts_pct_avg10_stint",
    "games_since_trade",
    "opponent_def_rating",
    "rest_days",
    "is_home",
]

# Rebotes e assistências continuam como taxa direta (produção por minuto) —
# a decomposição em volume/eficiência é específica de pontos.
SIMPLE_RATE_STATS = ["reb", "ast"]

# Fase 6 (opcional): no modo de intervalo "quantile", os intervalos de pontos
# vêm de um modelo direto de taxa (pts/minuto) treinado com o conjunto
# combinado de features de volume e eficiência — não a cadeia FGA×TS% usada
# para a previsão central, que continua igual nos dois modos. É uma
# simplificação deliberada: compor quantis de dois modelos encadeados
# (P10 de FGA × P10 de TS%, etc.) não tem uma justificativa estatística
# limpa, enquanto um único modelo de quantil sobre a taxa final tem.
PTS_QUANTILE_FEATURES = list(dict.fromkeys([*VOLUME_FEATURES, *EFFICIENCY_FEATURES]))

QUANTILE_ALPHAS = {"p10": 0.1, "p50": 0.5, "p90": 0.9}

MIN_RESIDUAL_STD_MINUTES = 3.0
MIN_RESIDUAL_STD_STAT = 1.5


@dataclass
class PlayerModelBundle:
    minutes_model: Pipeline
    fga_model: Pipeline
    ts_pct_model: Pipeline
    rate_models: dict
    metrics: dict
    residual_std: dict
    league_avg_opponent_def_rating: float
    interval_method: str = "normal"
    quantile_rate_models: dict | None = None


@dataclass(frozen=True)
class PlayerGamePrediction:
    minutes: float
    stats: dict
    stats_low: dict
    stats_high: dict
    confidence: str
    projected_fga: float
    projected_ts_pct: float


def _regression_pipeline() -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=2.0))])


def _quantile_pipeline(alpha: float) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                GradientBoostingRegressor(loss="quantile", alpha=alpha, random_state=0),
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
        f"{stat}_per_min_avg10",
        f"{stat}_per_min_avg10_stint",
        "games_since_trade",
        "opponent_def_rating",
        "rest_days",
        "is_home",
    ]


def _prepare(games: pd.DataFrame) -> pd.DataFrame:
    prepared = games.copy()
    prepared["is_home"] = prepared["is_home"].astype(int)
    return prepared


def _fta_per_fga_ratio(fga_rate: pd.Series, fta_rate: pd.Series) -> pd.Series:
    """Proporção histórica FTA/FGA — uma razão, não um modelo (seção 4.2 do
    planejamento: "estimar tentativas de lance livre a partir do volume de
    arremessos de quadra")."""
    return (fta_rate / fga_rate.replace(0, np.nan)).fillna(0.0)


def train_player_models(
    games_with_rolling_features: pd.DataFrame, interval_method: str = "normal"
) -> PlayerModelBundle:
    """Treina os modelos de projeção de jogador.

    `interval_method="normal"` (padrão): intervalos de pts/reb/ast vêm de
    Normal(0, erro histórico) em torno da previsão central — rápido, já
    validado nas fases anteriores. `interval_method="quantile"`: além dos
    modelos de sempre, treina modelos de quantil (P10/P90) por estatística
    para gerar intervalos assimétricos — mais caro (`GradientBoostingRegressor`
    em vez de Ridge, 3 modelos por estatística), pensado para comparar contra
    o modo normal via `walk_forward_evaluate` antes de virar padrão.
    """
    if interval_method not in ("normal", "quantile"):
        raise ValueError(f"interval_method inválido: {interval_method!r}")
    if len(games_with_rolling_features) < 50:
        raise ValueError("São necessários pelo menos 50 jogos para treinar o modelo.")

    ordered = (
        _prepare(games_with_rolling_features).sort_values("game_date").reset_index(drop=True)
    )
    split = max(int(len(ordered) * 0.8), 1)
    train_rows, test_rows = ordered.iloc[:split], ordered.iloc[split:]

    minutes_eval = _regression_pipeline().fit(train_rows[MINUTES_FEATURES], train_rows["minutes"])
    predicted_minutes = minutes_eval.predict(test_rows[MINUTES_FEATURES])

    metrics = {"minutes_mae": float(mean_absolute_error(test_rows["minutes"], predicted_minutes))}
    residual_std = {
        "minutes": max(
            float(np.std(test_rows["minutes"].to_numpy() - predicted_minutes)),
            MIN_RESIDUAL_STD_MINUTES,
        )
    }

    train_valid = train_rows[train_rows["minutes"] > 0]
    test_valid = test_rows[test_rows["minutes"] > 0]

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
    predicted_fga = np.maximum(0.0, predicted_fga_rate * test_valid["minutes"].to_numpy())

    # Eficiência: TS% (já usa o contexto do adversário).
    ts_pct_eval = _regression_pipeline().fit(
        train_pts_valid[EFFICIENCY_FEATURES], train_pts_valid["true_shooting_pct"]
    )
    predicted_ts_pct = np.clip(ts_pct_eval.predict(test_valid[EFFICIENCY_FEATURES]), 0.0, None)

    # FTA: proporção histórica FTA/FGA do próprio jogador, não um modelo.
    fta_ratio = _fta_per_fga_ratio(test_valid["fga_per_min_avg10"], test_valid["fta_per_min_avg10"])
    predicted_fta = predicted_fga * fta_ratio.to_numpy()

    # PTS = TS% × 2 × (FGA + 0,44 × FTA) — inversão direta da definição de TS%
    # já usada em src/player_metrics.py::add_efficiency_metrics.
    predicted_pts = np.maximum(0.0, predicted_ts_pct * 2 * (predicted_fga + 0.44 * predicted_fta))

    metrics["pts_mae"] = float(mean_absolute_error(test_valid["pts"], predicted_pts))
    residual_std["pts"] = max(
        float(np.std(test_valid["pts"].to_numpy() - predicted_pts)), MIN_RESIDUAL_STD_STAT
    )

    rate_models_eval = {}
    for stat in SIMPLE_RATE_STATS:
        features = _rate_features(stat)
        model = _regression_pipeline().fit(
            train_valid[features], train_valid[stat] / train_valid["minutes"]
        )
        predicted_rate = model.predict(test_valid[features])
        predicted_stat = predicted_rate * test_valid["minutes"].to_numpy()

        metrics[f"{stat}_mae"] = float(mean_absolute_error(test_valid[stat], predicted_stat))
        residual_std[stat] = max(
            float(np.std(test_valid[stat].to_numpy() - predicted_stat)), MIN_RESIDUAL_STD_STAT
        )
        rate_models_eval[stat] = model

    all_valid = ordered[ordered["minutes"] > 0]
    all_pts_valid = all_valid[all_valid["true_shooting_pct"].notna()]

    final_quantile_rate_models = None
    if interval_method == "quantile":
        final_quantile_rate_models = {
            "pts": _fit_quantile_models(
                all_pts_valid[PTS_QUANTILE_FEATURES],
                all_pts_valid["pts"] / all_pts_valid["minutes"],
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
    final_rate_models = {
        stat: clone(rate_models_eval[stat]).fit(
            all_valid[_rate_features(stat)], all_valid[stat] / all_valid["minutes"]
        )
        for stat in SIMPLE_RATE_STATS
    }

    return PlayerModelBundle(
        minutes_model=final_minutes_model,
        fga_model=final_fga_model,
        ts_pct_model=final_ts_pct_model,
        rate_models=final_rate_models,
        metrics=metrics,
        residual_std=residual_std,
        league_avg_opponent_def_rating=float(ordered["opponent_def_rating"].mean()),
        interval_method=interval_method,
        quantile_rate_models=final_quantile_rate_models,
    )


def predict_from_features(bundle: PlayerModelBundle, rows: pd.DataFrame) -> pd.DataFrame:
    """Previsão em lote (minutos, pontos, rebotes, assistências) a partir de
    linhas de features já calculadas.

    Função de baixo nível compartilhada por `predict_player_game` (que monta
    uma linha a partir do snapshot ao vivo) e por `walk_forward_evaluate`
    (que aplica direto às linhas de treino/avaliação já existentes) — a
    álgebra da cadeia de pontos (minutos → FGA → TS%) fica escrita uma vez só.
    """
    prepared = _prepare(rows)

    predicted_minutes = np.maximum(0.0, bundle.minutes_model.predict(prepared[MINUTES_FEATURES]))

    predicted_fga_rate = np.maximum(0.0, bundle.fga_model.predict(prepared[VOLUME_FEATURES]))
    predicted_fga = predicted_fga_rate * predicted_minutes

    predicted_ts_pct = np.clip(bundle.ts_pct_model.predict(prepared[EFFICIENCY_FEATURES]), 0.0, None)

    fta_ratio = _fta_per_fga_ratio(
        prepared["fga_per_min_avg10"], prepared["fta_per_min_avg10"]
    ).to_numpy()
    predicted_fta = predicted_fga * fta_ratio
    predicted_pts = np.maximum(0.0, predicted_ts_pct * 2 * (predicted_fga + 0.44 * predicted_fta))

    result = pd.DataFrame(
        {
            "minutes": predicted_minutes,
            "fga": predicted_fga,
            "ts_pct": predicted_ts_pct,
            "pts": predicted_pts,
        },
        index=prepared.index,
    )
    for stat in SIMPLE_RATE_STATS:
        rate = bundle.rate_models[stat].predict(prepared[_rate_features(stat)])
        result[stat] = np.maximum(0.0, rate * predicted_minutes)
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
            p10_value = np.maximum(0.0, p10_rate * minutes)
            p90_value = np.maximum(0.0, p90_rate * minutes)
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
                "fga_per_min_avg10": snapshot["fga_per_min_avg10"],
                "fga_per_min_avg10_stint": snapshot["fga_per_min_avg10_stint"],
                "fta_per_min_avg10": snapshot["fta_per_min_avg10"],
                "ts_pct_avg10": snapshot["ts_pct_avg10"],
                "ts_pct_avg10_stint": snapshot["ts_pct_avg10_stint"],
                "usg_pct_avg10": snapshot["usg_pct_avg10"],
                "usg_pct_avg10_stint": snapshot["usg_pct_avg10_stint"],
                "reb_per_min_avg10": snapshot["reb_per_min_avg10"],
                "reb_per_min_avg10_stint": snapshot["reb_per_min_avg10_stint"],
                "ast_per_min_avg10": snapshot["ast_per_min_avg10"],
                "ast_per_min_avg10_stint": snapshot["ast_per_min_avg10_stint"],
                "games_since_trade": snapshot["games_since_trade"],
                "opponent_def_rating": opponent_def_rating,
                "rest_days": rest_days,
                "is_home": int(is_home),
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

    minutes_margin = 1.28 * bundle.residual_std["minutes"]
    if predicted_minutes < 1.0:
        confidence = "Baixa"
    else:
        ratio = minutes_margin / predicted_minutes
        confidence = "Baixa" if ratio > 0.5 else "Média" if ratio > 0.25 else "Alta"

    return PlayerGamePrediction(
        minutes=predicted_minutes,
        stats=stats,
        stats_low=stats_low,
        stats_high=stats_high,
        confidence=confidence,
        projected_fga=float(predicted_row["fga"]),
        projected_ts_pct=float(predicted_row["ts_pct"]),
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


def walk_forward_evaluate(
    games_with_features: pd.DataFrame,
    n_folds: int = 5,
    min_train_games: int = 200,
    interval_method: str = "normal",
) -> dict:
    """Validação progressiva: treina até uma data, avalia no pedaço seguinte, avança.

    Mais confiável que o único split 80/20 usado por `train_player_models`
    para reportar métricas (que pode calhar de cair num trecho fácil ou
    difícil da base) — mas custa `n_folds` retreinos completos, por isso é
    pensada para rodar offline (`scripts/retrain_models.py`), não a cada
    carregamento da página.

    `interval_method` é repassado a `train_player_models` em cada fold. Além
    do MAE, calcula a **cobertura do intervalo** de pts/reb/ast — a fração de
    jogos reais que caiu dentro do intervalo previsto (num intervalo de ~80%
    bem calibrado, a cobertura deveria ficar perto de 0,80). É o critério do
    plano para decidir entre `"normal"` e `"quantile"`: rodar os dois modos e
    comparar cobertura, não só MAE (os dois modos tendem a um MAE parecido,
    já que a previsão central não muda).

    Devolve `{"folds": [...], "aggregate": {...}}`, com o MAE/cobertura de
    cada fold (tamanho de treino crescente a cada fold) e a média entre os
    folds.
    """
    ordered = games_with_features.sort_values("game_date").reset_index(drop=True)
    if len(ordered) < min_train_games * 2:
        raise ValueError(
            f"São necessários pelo menos {min_train_games * 2} jogos para validação "
            "walk-forward."
        )

    boundaries = np.linspace(min_train_games, len(ordered), n_folds + 1, dtype=int)
    stats_to_evaluate = ["minutes", "pts", *SIMPLE_RATE_STATS]
    fold_results = []

    for fold_index in range(n_folds):
        train_end = boundaries[fold_index]
        test_end = boundaries[fold_index + 1]
        if test_end <= train_end:
            continue

        train_fold = ordered.iloc[:train_end]
        test_fold = ordered.iloc[train_end:test_end]
        test_fold_valid = test_fold[test_fold["minutes"] > 0]
        if test_fold_valid.empty:
            continue

        bundle = train_player_models(train_fold, interval_method=interval_method)
        predicted = predict_from_features(bundle, test_fold_valid)
        intervals = _predict_intervals(bundle, test_fold_valid, predicted)

        fold_metrics: dict[str, int | float] = {
            "fold": fold_index,
            "n_train": int(train_end),
            "n_test": int(len(test_fold_valid)),
        }
        for stat in stats_to_evaluate:
            fold_metrics[f"{stat}_mae"] = float(
                mean_absolute_error(test_fold_valid[stat], predicted[stat])
            )
        for stat in ("pts", *SIMPLE_RATE_STATS):
            low, high = intervals[stat]
            inside = (test_fold_valid[stat] >= low) & (test_fold_valid[stat] <= high)
            fold_metrics[f"{stat}_interval_coverage"] = float(inside.mean())
        fold_results.append(fold_metrics)

    if not fold_results:
        raise ValueError("Não foi possível formar nenhum fold de validação walk-forward.")

    aggregate = {
        f"{stat}_mae": float(np.mean([fold[f"{stat}_mae"] for fold in fold_results]))
        for stat in stats_to_evaluate
    }
    for stat in ("pts", *SIMPLE_RATE_STATS):
        aggregate[f"{stat}_interval_coverage"] = float(
            np.mean([fold[f"{stat}_interval_coverage"] for fold in fold_results])
        )
    aggregate["n_folds"] = len(fold_results)

    return {"folds": fold_results, "aggregate": aggregate}
