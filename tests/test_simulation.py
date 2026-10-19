import numpy as np
import pandas as pd

from src.model import GamePrediction
from src.simulation import simulate_score_distribution


def _prediction(home_score: float = 112.0, away_score: float = 108.0) -> GamePrediction:
    return GamePrediction(
        home_win_probability=0.6,
        away_win_probability=0.4,
        home_score=home_score,
        away_score=away_score,
        home_score_low=home_score - 10,
        home_score_high=home_score + 10,
        away_score_low=away_score - 10,
        away_score_high=away_score + 10,
        confidence="Média",
        factors=[],
    )


def test_simulate_score_distribution_returns_expected_shape_and_columns():
    result = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, simulations=500)
    assert len(result) == 500
    assert set(result.columns) == {"home_score", "away_score", "margin", "home_win"}


def test_simulate_score_distribution_never_returns_negative_scores():
    # Média baixa e desvio grande: sem o `np.maximum(0, ...)`, a Normal geraria
    # placares negativos com frequência.
    result = simulate_score_distribution(
        _prediction(home_score=5.0, away_score=3.0), home_std=20.0, away_std=20.0, simulations=2_000
    )
    assert (result["home_score"] >= 0).all()
    assert (result["away_score"] >= 0).all()


def test_simulate_score_distribution_never_produces_a_tie():
    # A regra de desempate (soma 1-3 pontos ao mandante em caso de empate)
    # precisa eliminar 100% dos empates, não só reduzi-los.
    result = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, simulations=5_000)
    assert (result["home_score"] != result["away_score"]).all()


def test_simulate_score_distribution_margin_and_home_win_are_consistent():
    result = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, simulations=1_000)
    assert (result["margin"] == result["home_score"] - result["away_score"]).all()
    assert (result["home_win"] == (result["margin"] > 0)).all()


def test_simulate_score_distribution_is_deterministic_for_a_given_seed():
    result_a = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, seed=7)
    result_b = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, seed=7)
    pd.testing.assert_frame_equal(result_a, result_b)


def test_simulate_score_distribution_different_seeds_produce_different_results():
    result_a = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, seed=1)
    result_b = simulate_score_distribution(_prediction(), home_std=10.0, away_std=10.0, seed=2)
    assert not result_a["home_score"].equals(result_b["home_score"])


def test_simulate_score_distribution_centers_on_the_predicted_score():
    # Verificação estatística leve: com desvio pequeno e amostra grande, a
    # média simulada deve ficar perto da previsão central.
    prediction = _prediction(home_score=110.0, away_score=100.0)
    result = simulate_score_distribution(prediction, home_std=3.0, away_std=3.0, simulations=10_000)
    assert np.isclose(result["home_score"].mean(), 110.0, atol=1.0)
    assert np.isclose(result["away_score"].mean(), 100.0, atol=1.0)
