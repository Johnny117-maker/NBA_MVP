import pytest

from src.data import available_teams, generate_demo_games, team_snapshot
from src.model import predict_game, train_models
from src.simulation import simulate_score_distribution


@pytest.fixture(scope="module")
def setup_model():
    games = generate_demo_games(number_of_games=220)
    bundle = train_models(games)
    teams = available_teams(games)
    return games, bundle, teams


def test_prediction_probabilities_sum_to_one(setup_model):
    games, bundle, teams = setup_model
    prediction = predict_game(
        bundle,
        team_snapshot(games, teams[0]),
        team_snapshot(games, teams[1]),
    )
    assert 0 <= prediction.home_win_probability <= 1
    assert 0 <= prediction.away_win_probability <= 1
    assert prediction.home_win_probability + prediction.away_win_probability == pytest.approx(1)


def test_score_intervals_are_ordered(setup_model):
    games, bundle, teams = setup_model
    prediction = predict_game(
        bundle,
        team_snapshot(games, teams[2]),
        team_snapshot(games, teams[3]),
    )
    assert prediction.home_score_low < prediction.home_score < prediction.home_score_high
    assert prediction.away_score_low < prediction.away_score < prediction.away_score_high


def test_simulation_returns_expected_rows(setup_model):
    games, bundle, teams = setup_model
    prediction = predict_game(
        bundle,
        team_snapshot(games, teams[4]),
        team_snapshot(games, teams[5]),
    )
    result = simulate_score_distribution(prediction, 8.0, 8.0, simulations=500)
    assert len(result) == 500
    assert not (result["home_score"] == result["away_score"]).any()

