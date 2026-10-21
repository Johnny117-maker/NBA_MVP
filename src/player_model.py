from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SEASON_BASELINE_FEATURES = [
    "prev_season_pts_avg",
    "prev_season_reb_avg",
    "prev_season_ast_avg",
    "prev_season_minutes_avg",
    "prev_season_pts_per_min",
    "prev_season_reb_per_min",
    "prev_season_ast_per_min",
    "prev_season_games",
]

MINUTES_FEATURES = [
    "minutes_avg5",
    "minutes_avg10",
    "minutes_avg5_stint",
    "minutes_avg10_stint",
    "starter_rate_avg10",
    "starter_rate_avg10_stint",
    "games_since_trade",
    "rest_days",
    "is_back_to_back",
    "is_long_rest",
    "is_home",
    "prev_season_minutes_avg",
    "prev_season_games",
]

# Janelas curtas captam mudanças de função/volume, enquanto as EMAs de 10
# jogos estabilizam o sinal. A cadeia volume × eficiência é mantida como
# referência interpretável; a projeção central também testa um regressor direto.
VOLUME_FEATURES = [
    "fga_per_min_avg3",
    "fga_per_min_avg5",
    "fga_per_min_avg10",
    "fga_per_min_avg5_stint",
    "fga_per_min_avg10_stint",
    "fta_per_min_avg3",
    "fta_per_min_avg5",
    "fta_per_min_avg10",
    "usg_pct_avg5",
    "usg_pct_avg10",
    "usg_pct_avg5_stint",
    "usg_pct_avg10_stint",
    "games_since_trade",
    "rest_days",
    "is_back_to_back",
    "is_long_rest",
    "is_home",
    "prev_season_pts_avg",
    "prev_season_pts_per_min",
    "prev_season_minutes_avg",
    "prev_season_games",
]
EFFICIENCY_FEATURES = [
    "ts_pct_avg3",
    "ts_pct_avg5",
    "ts_pct_avg10",
    "ts_pct_avg3_stint",
    "ts_pct_avg5_stint",
    "ts_pct_avg10_stint",
    "pts_per_min_avg3",
    "pts_per_min_avg5",
    "pts_per_min_avg10",
    "pts_per_min_avg5_stint",
    "opponent_def_rating",
    "rest_days",
    "is_back_to_back",
    "is_long_rest",
    "is_home",
    "prev_season_pts_avg",
    "prev_season_pts_per_min",
    "prev_season_minutes_avg",
    "prev_season_games",
]

# Rebotes e assistências continuam como taxa direta (produção por minuto) —
# a decomposição em volume/eficiência é específica de pontos.
SIMPLE_RATE_STATS = ["reb", "ast"]

# Modelo alternativo de pontos por minuto: inclui oportunidade (minutos,
# titularidade/rotação), volume, eficiência e contexto pré-jogo.
PTS_DIRECT_FEATURES = list(
    dict.fromkeys(
        [*MINUTES_FEATURES, *VOLUME_FEATURES, *EFFICIENCY_FEATURES, *SEASON_BASELINE_FEATURES]
    )
)

# No modo quantile, os limites usam a mesma família de características do
# modelo direto. Evita quantis compostos de modelos diferentes (FGA × TS%).
PTS_QUANTILE_FEATURES = list(PTS_DIRECT_FEATURES)

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
    direct_pts_model: HistGradientBoostingRegressor | None = None
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
    chain_pts: float


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

    minutes_eval = _regression_pipeline().fit(train_rows[MINUTES_FEATURES], train_rows["minutes"])
    predicted_minutes_raw = minutes_eval.predict(test_rows[MINUTES_FEATURES])
    predicted_minutes = _calibrate_minutes_predictions(
        predicted_minutes_raw, _prepare(test_rows)
    )
    predicted_minutes_by_index = pd.Series(predicted_minutes, index=test_rows.index)

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
    test_predicted_minutes = predicted_minutes_by_index.loc[test_valid.index].to_numpy()
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
    predicted_pts = _blend_season_baseline(
        "pts", predicted_pts_unblended, test_predicted_minutes, _prepare(test_valid)
    )

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

    return PlayerModelBundle(
        minutes_model=final_minutes_model,
        fga_model=final_fga_model,
        ts_pct_model=final_ts_pct_model,
        rate_models=final_rate_models,
        metrics=metrics,
        residual_std=residual_std,
        league_avg_opponent_def_rating=float(ordered["opponent_def_rating"].mean()),
        direct_pts_model=final_direct_pts_model,
        interval_method=interval_method,
        quantile_rate_models=final_quantile_rate_models,
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
            prediction_records.append(record)

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
        fold_results.append(fold_metrics)

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

