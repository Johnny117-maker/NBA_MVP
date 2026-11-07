import pandas as pd
import pytest
from scipy.stats import norm

from src.data import available_teams, generate_demo_games, load_real_games, team_snapshot
from src.model import (
    FEATURE_LABELS,
    FEATURE_NAMES,
    SCORE_FEATURE_NAMES,
    build_score_features,
    matchup_score_features,
    predict_game,
    temporal_split_index,
    train_models,
)
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


def test_total_uses_absolute_context_while_winner_uses_relative_features(setup_model):
    games, bundle, teams = setup_model
    assert bundle.win_model.feature_names_in_.tolist() == FEATURE_NAMES
    assert bundle.total_model.feature_names_in_.tolist() == SCORE_FEATURE_NAMES
    home, away = (team_snapshot(games, team) for team in teams[:2])
    baseline = predict_game(bundle, home, away)
    # O mesmo aumento nos dois times preserva as diferenças, mas altera o
    # nível esperado do placar: limitação que motivou o modelo do total.
    higher = [dict(snapshot) for snapshot in (home, away)]
    for snapshot in higher:
        for key in ("off_rating", "def_rating", "points_for"):
            snapshot[key] += 20
    prediction = predict_game(bundle, *higher)
    assert prediction.home_win_probability == pytest.approx(baseline.home_win_probability)
    assert prediction.home_score + prediction.away_score > baseline.home_score + baseline.away_score + 5


def test_winner_and_scores_come_from_the_same_margin(setup_model):
    games, bundle, teams = setup_model
    prediction = predict_game(bundle, team_snapshot(games, teams[6]), team_snapshot(games, teams[7]))
    margin = prediction.home_score - prediction.away_score
    expected = norm.cdf(margin / bundle.win_model.sigma)
    assert prediction.home_win_probability == pytest.approx(expected)
    # O favorito nunca perde no placar previsto.
    assert (margin > 0) == (prediction.home_win_probability > 0.5)


def test_stronger_elo_raises_the_win_probability(setup_model):
    games, bundle, teams = setup_model
    home, away = (team_snapshot(games, team) for team in teams[:2])
    weaker, stronger = dict(home, elo=1400.0), dict(home, elo=1600.0)
    low = predict_game(bundle, weaker, away)
    high = predict_game(bundle, stronger, away)
    assert high.home_win_probability > low.home_win_probability
    assert high.home_score - high.away_score > low.home_score - low.away_score


def test_factors_explain_the_margin_in_standard_deviations(setup_model):
    games, bundle, teams = setup_model
    home, away = (team_snapshot(games, team) for team in teams[:2])
    prediction = predict_game(bundle, home, away)
    assert {label for label, _ in prediction.factors} == set(FEATURE_LABELS.values())
    magnitudes = [abs(value) for _, value in prediction.factors]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_training_metrics_include_margin_error(setup_model):
    _, bundle, _ = setup_model
    for key in ("accuracy", "log_loss", "brier_score", "home_points_mae", "away_points_mae", "margin_mae"):
        assert key in bundle.metrics
    assert bundle.metrics["score_model_version"] == 3


def test_score_inputs_do_not_use_the_target_games_points():
    games = generate_demo_games(100)
    before = build_score_features(games)
    day = games.iloc[50]["game_date"]
    changed = games.copy()
    changed.loc[changed["game_date"].ge(day), ["home_points", "away_points"]] = 999
    after = build_score_features(changed)
    pd.testing.assert_frame_equal(before.loc[games["game_date"].le(day)],
                                  after.loc[games["game_date"].le(day)])


def test_validation_keeps_a_whole_date_out_of_training():
    dates = pd.DataFrame({"game_date": pd.to_datetime(["2026-01-01"] * 79
                                                     + ["2026-01-02"] * 15
                                                     + ["2026-01-03"] * 6)})
    split = temporal_split_index(dates)
    assert split == 79
    assert dates.iloc[:split]["game_date"].max() < dates.iloc[split:]["game_date"].min()
    with pytest.raises(ValueError, match="duas datas"):
        temporal_split_index(dates.head(50))


def test_next_game_snapshot_matches_training_inputs_without_averaging_rolling_averages(app_db):
    games = load_real_games(app_db)
    target = games.iloc[-1]
    history = games[games["game_date"].lt(target["game_date"])]
    features = matchup_score_features(
        team_snapshot(history, target["home_team"]),
        team_snapshot(history, target["away_team"]),
        int(target["home_rest_days"]), int(target["away_rest_days"]),
    )
    expected = build_score_features(games).tail(1).reset_index(drop=True)
    pd.testing.assert_frame_equal(features, expected)

