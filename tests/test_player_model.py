import numpy as np
import pandas as pd
import pytest

from src.data import generate_demo_games
from src.player_data import generate_demo_player_games
from src.player_features import add_opponent_context, add_rolling_features
from src.player_metrics import add_efficiency_metrics, player_snapshot
from src.player_model import (
    PTS_QUANTILE_FEATURES,
    SIMPLE_RATE_STATS,
    PlayerModelBundle,
    _calibrate_minutes_predictions,
    _prediction_confidence,
    _predict_intervals,
    _rate_features,
    over_probability,
    predict_player_game,
    range_probabilities,
    train_player_models,
    walk_forward_evaluate,
    _temporal_train_test_split,
)


@pytest.fixture(scope="module")
def setup_model():
    # Mesma ordem do pipeline real (src/player_data.py::load_player_games):
    # eficiência primeiro (dá o true_shooting_pct que os modelos de volume/
    # eficiência da fase 4 precisam), rolling e contexto do adversário depois.
    raw = add_efficiency_metrics(generate_demo_player_games(games_per_team=25))
    team_games = generate_demo_games(number_of_games=300)
    games_with_features = add_opponent_context(add_rolling_features(raw), team_games)
    bundle = train_player_models(games_with_features)
    return raw, bundle


@pytest.fixture(scope="module")
def setup_quantile_model():
    raw = add_efficiency_metrics(generate_demo_player_games(games_per_team=25))
    team_games = generate_demo_games(number_of_games=300)
    games_with_features = add_opponent_context(add_rolling_features(raw), team_games)
    bundle = train_player_models(games_with_features, interval_method="quantile")
    return raw, bundle


def test_metrics_are_finite_and_non_negative(setup_model):
    _, bundle = setup_model
    for value in bundle.metrics.values():
        assert value >= 0
        assert value == value  # não é NaN
    assert "pts_baseline_mae" in bundle.metrics
    assert "pts_chain_mae" in bundle.metrics
    assert bundle.direct_pts_model is not None


def test_prediction_is_non_negative_and_intervals_are_ordered(setup_model):
    raw, bundle = setup_model
    player_id = raw["player_id"].iloc[0]
    snapshot = player_snapshot(raw, player_id)

    prediction = predict_player_game(bundle, snapshot, is_home=True, rest_days=2)

    assert prediction.minutes >= 0
    for stat in ("pts", "reb", "ast"):
        assert prediction.stats[stat] >= 0
        assert prediction.stats_low[stat] <= prediction.stats[stat] <= prediction.stats_high[stat]
    assert prediction.confidence in {"Baixa", "Média", "Alta"}
    assert prediction.chain_pts >= 0


def test_higher_usage_player_projects_more_points_than_bench_player(setup_model):
    raw, bundle = setup_model
    # No gerador demo, o player_id 1 de cada time é sempre o arquétipo "Astro".
    astro_snapshot = player_snapshot(raw, 1)
    bench_snapshot = player_snapshot(raw, 5)  # 5º jogador do primeiro time é "Banco"

    astro_prediction = predict_player_game(bundle, astro_snapshot, is_home=True, rest_days=2)
    bench_prediction = predict_player_game(bundle, bench_snapshot, is_home=True, rest_days=2)

    assert astro_prediction.stats["pts"] > bench_prediction.stats["pts"]


def test_opponent_def_rating_shifts_the_prediction(setup_model):
    raw, bundle = setup_model
    snapshot = player_snapshot(raw, 1)

    against_weak_defense = predict_player_game(
        bundle, snapshot, is_home=True, rest_days=2, opponent_def_rating=130.0
    )
    against_strong_defense = predict_player_game(
        bundle, snapshot, is_home=True, rest_days=2, opponent_def_rating=95.0
    )

    assert against_weak_defense.stats["pts"] != against_strong_defense.stats["pts"]



def test_temporal_split_never_separates_rows_from_the_same_date():
    rows = pd.DataFrame(
        {
            "game_date": pd.to_datetime([
                "2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02",
                "2024-01-03", "2024-01-03", "2024-01-04", "2024-01-04",
                "2024-01-05", "2024-01-05",
            ]),
            "minutes": list(range(10)),
        }
    )
    train_rows, test_rows = _temporal_train_test_split(rows, train_fraction=0.6)
    assert train_rows["game_date"].max() < test_rows["game_date"].min()
    assert set(train_rows["game_date"]).isdisjoint(set(test_rows["game_date"]))

def test_range_probabilities_sum_to_one():
    buckets = range_probabilities(predicted_value=25.0, residual_std=3.0, n_buckets=5)
    assert len(buckets) == 5
    assert sum(bucket["probability"] for bucket in buckets) == pytest.approx(1.0, abs=1e-9)


def test_range_probabilities_center_bucket_contains_the_prediction():
    buckets = range_probabilities(predicted_value=25.0, residual_std=3.0, n_buckets=5)
    center_bucket = buckets[2]
    assert center_bucket["low"] <= 25.0 <= center_bucket["high"]
    # A faixa central deveria concentrar mais probabilidade que as extremas.
    assert center_bucket["probability"] > buckets[0]["probability"]
    assert center_bucket["probability"] > buckets[-1]["probability"]


def test_range_probabilities_widen_with_more_uncertainty():
    tight = range_probabilities(predicted_value=25.0, residual_std=1.0, n_buckets=5)
    loose = range_probabilities(predicted_value=25.0, residual_std=8.0, n_buckets=5)

    tight_width = tight[2]["high"] - tight[2]["low"]
    loose_width = loose[2]["high"] - loose[2]["low"]
    assert loose_width > tight_width


def test_range_probabilities_labels_are_ordered_and_readable():
    buckets = range_probabilities(predicted_value=25.0, residual_std=3.0, n_buckets=5)
    labels = [bucket["label"] for bucket in buckets]
    assert labels[0].startswith("≤")
    assert labels[-1].startswith("≥")
    for label in labels[1:-1]:
        assert "–" in label


def test_walk_forward_evaluate_returns_one_result_per_fold_with_growing_train_size():
    raw = add_efficiency_metrics(generate_demo_player_games(games_per_team=25))
    team_games = generate_demo_games(number_of_games=300)
    games_with_features = add_opponent_context(add_rolling_features(raw), team_games)

    result = walk_forward_evaluate(games_with_features, n_folds=4, min_train_games=200)

    assert len(result["folds"]) == 4
    train_sizes = [fold["n_train"] for fold in result["folds"]]
    assert train_sizes == sorted(train_sizes)
    assert len(set(train_sizes)) == len(train_sizes)  # estritamente crescente, sem repetir

    for stat in ("minutes_mae", "pts_mae", "reb_mae", "ast_mae"):
        assert result["aggregate"][stat] >= 0
        assert result["aggregate"][stat] == result["aggregate"][stat]  # não é NaN
    assert result["aggregate"]["n_folds"] == 4
    assert result["aggregate"]["pts_baseline_mae"] >= 0
    assert result["aggregate"]["pts_chain_mae"] >= 0
    assert not result["predictions"].empty
    assert {"game_date", "player_name", "predicted_pts", "actual_pts", "pts_absolute_error"} <= set(
        result["predictions"].columns
    )


def test_quantile_interval_method_trains_all_three_percentiles_per_stat(setup_quantile_model):
    _, bundle = setup_quantile_model
    assert bundle.interval_method == "quantile"
    assert set(bundle.quantile_rate_models) == {"pts", "reb", "ast"}
    for stat_models in bundle.quantile_rate_models.values():
        assert set(stat_models) == {"p10", "p50", "p90"}


def test_quantile_mode_predictions_are_non_negative_and_intervals_are_ordered(setup_quantile_model):
    raw, bundle = setup_quantile_model
    for player_id in (1, 5):  # astro e jogador de banco (arquétipos do gerador demo)
        snapshot = player_snapshot(raw, player_id)
        prediction = predict_player_game(bundle, snapshot, is_home=True, rest_days=2)

        assert prediction.minutes >= 0
        for stat in ("pts", "reb", "ast"):
            assert prediction.stats[stat] >= 0
            assert (
                prediction.stats_low[stat] <= prediction.stats[stat] <= prediction.stats_high[stat]
            )


class _FixedPipeline:
    """Modelo falso que ignora as features e sempre devolve o mesmo valor —
    usado só para controlar exatamente o que P10/P50/P90 preveem, sem
    depender de um modelo de verdade cruzar os quantis por acaso."""

    def __init__(self, value):
        self._value = value

    def predict(self, X):
        return np.full(len(X), self._value)


def test_predict_intervals_enforces_order_even_if_the_raw_quantiles_cross():
    """Reproduz o problema conhecido de quantis cruzados: troca P10/P90 na
    mão (P10 previsto MAIOR que P90 previsto) e confere que a função de
    intervalo devolve os dois na ordem certa mesmo assim."""
    quantile_rate_models = {
        stat: {"p10": _FixedPipeline(0.9), "p50": _FixedPipeline(0.5), "p90": _FixedPipeline(0.1)}
        for stat in ("pts", *SIMPLE_RATE_STATS)
    }
    bundle = PlayerModelBundle(
        minutes_model=_FixedPipeline(30.0),
        fga_model=_FixedPipeline(0.5),
        ts_pct_model=_FixedPipeline(0.55),
        rate_models={stat: _FixedPipeline(0.2) for stat in SIMPLE_RATE_STATS},
        metrics={},
        residual_std={},
        league_avg_opponent_def_rating=110.0,
        interval_method="quantile",
        quantile_rate_models=quantile_rate_models,
    )

    # Colunas reais não importam: _FixedPipeline ignora X e sempre devolve o
    # mesmo valor — só precisamos de qualquer linha com as colunas que
    # _predict_intervals vai tentar selecionar.
    needed_columns = set(PTS_QUANTILE_FEATURES)
    for stat in SIMPLE_RATE_STATS:
        needed_columns |= set(_rate_features(stat))
    rows = pd.DataFrame([{column: 0.0 for column in needed_columns}])
    rows["is_home"] = True
    predicted = pd.DataFrame({"minutes": [30.0]})

    intervals = _predict_intervals(bundle, rows, predicted)
    for stat in ("pts", *SIMPLE_RATE_STATS):
        low, high = intervals[stat]
        assert low.iloc[0] <= high.iloc[0]


def test_walk_forward_evaluate_reports_interval_coverage_in_both_modes():
    raw = add_efficiency_metrics(generate_demo_player_games(games_per_team=25))
    team_games = generate_demo_games(number_of_games=300)
    games_with_features = add_opponent_context(add_rolling_features(raw), team_games)

    for method in ("normal", "quantile"):
        result = walk_forward_evaluate(
            games_with_features, n_folds=2, min_train_games=200, interval_method=method
        )
        for stat in ("pts", "reb", "ast"):
            coverage = result["aggregate"][f"{stat}_interval_coverage"]
            assert 0.0 <= coverage <= 1.0


def test_over_probability_is_fifty_fifty_when_line_matches_the_prediction():
    probability = over_probability(predicted_value=20.0, residual_std=5.0, line=20.0)
    assert probability == pytest.approx(0.5, abs=1e-9)


def test_over_probability_rises_as_the_line_drops_below_the_prediction():
    high_line = over_probability(predicted_value=20.0, residual_std=5.0, line=25.0)
    low_line = over_probability(predicted_value=20.0, residual_std=5.0, line=15.0)

    assert 0.0 <= high_line < 0.5 < low_line <= 1.0


def test_over_probability_moves_toward_fifty_fifty_as_uncertainty_grows():
    offset_line = 24.0  # 4 pontos acima da previsão
    tight_model = over_probability(predicted_value=20.0, residual_std=2.0, line=offset_line)
    loose_model = over_probability(predicted_value=20.0, residual_std=20.0, line=offset_line)

    # Um modelo mais incerto (residual_std maior) tem menos convicção de que o
    # line vai ficar longe da previsão, então a probabilidade fica mais perto
    # de 50% do que a de um modelo mais preciso, para o mesmo line.
    assert abs(loose_model - 0.5) < abs(tight_model - 0.5)


def test_over_probability_handles_zero_uncertainty():
    assert over_probability(predicted_value=20.0, residual_std=0.0, line=19.0) == 1.0
    assert over_probability(predicted_value=20.0, residual_std=0.0, line=21.0) == 0.0


def test_walk_forward_evaluate_requires_enough_games():
    tiny = add_efficiency_metrics(generate_demo_player_games(games_per_team=2))
    team_games = generate_demo_games(number_of_games=60)
    games_with_features = add_opponent_context(add_rolling_features(tiny), team_games)

    # min_train_games * 2 é bem maior que a base fabricada (poucas centenas de
    # linhas) — não dá para formar nem o primeiro fold.
    with pytest.raises(ValueError):
        walk_forward_evaluate(games_with_features, n_folds=5, min_train_games=10_000)


def test_previous_season_blend_starts_more_conservative_after_team_change():
    from src.player_model import _blend_season_baseline, _season_baseline_weight

    rows = pd.DataFrame(
        {
            "games_since_trade": [0, 5, 10],
            "prev_season_games": [82, 82, 82],
            "prev_season_pts_per_min": [0.60, 0.60, 0.60],
            "prev_season_reb_per_min": [0.20, 0.20, 0.20],
            "prev_season_ast_per_min": [0.10, 0.10, 0.10],
        }
    )
    weights = _season_baseline_weight(rows)
    assert weights.tolist() == pytest.approx([0.60, 0.40, 0.20])

    blended = _blend_season_baseline(
        "pts", model_prediction=np.array([30.0, 30.0, 30.0]),
        predicted_minutes=np.array([30.0, 30.0, 30.0]), prepared=rows,
    )
    # Baseline é 18 pontos; com mais jogos no stint, a projeção acompanha mais
    # o modelo dinâmico (30 pontos) e reduz o peso da temporada anterior.
    assert blended[0] == pytest.approx(22.8)
    assert blended[1] == pytest.approx(25.2)
    assert blended[2] == pytest.approx(27.6)



def test_minutes_calibration_moves_model_toward_recent_rotation_context():
    features = pd.DataFrame(
        [{
            "minutes_avg5": 32.0,
            "minutes_avg10": 30.0,
            "minutes_avg5_stint": 36.0,
            "minutes_avg10_stint": 34.0,
            "prev_season_minutes_avg": 31.0,
            "games_since_trade": 8.0,
            "is_home": True,
            "rest_days": 2,
        }]
    )
    calibrated = _calibrate_minutes_predictions(np.array([25.0]), features)
    assert calibrated[0] > 25.0
    assert calibrated[0] < 36.0


def test_prediction_confidence_is_low_with_little_history():
    confidence = _prediction_confidence(
        {"minutes": 4.0, "pts": 5.0, "reb": 2.0, "ast": 2.0},
        predicted_minutes=30.0,
        stats={"pts": 25.0, "reb": 8.0, "ast": 5.0},
        context={"games": 3, "games_since_trade": 2},
    )
    assert confidence == "Baixa"


def test_prediction_confidence_can_be_high_with_stable_history_and_low_error():
    confidence = _prediction_confidence(
        {"minutes": 1.0, "pts": 2.0, "reb": 1.0, "ast": 1.0},
        predicted_minutes=32.0,
        stats={"pts": 25.0, "reb": 8.0, "ast": 5.0},
        context={"games": 100, "games_since_trade": 20},
    )
    assert confidence == "Alta"
