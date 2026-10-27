import pandas as pd
import pytest

from src.data import REQUIRED_COLUMNS, team_snapshot
from src.features import DEFAULT_RATING, engineer_features, pregame_scoring_averages


def _raw_games() -> pd.DataFrame:
    # Celtics jogam três vezes; Knicks e Heat aparecem como adversários.
    return pd.DataFrame(
        [
            {
                "game_id": "1",
                "game_date": "2024-10-01",
                "season": "2024-25",
                "home_team": "Celtics",
                "away_team": "Knicks",
                "home_points": 110,
                "away_points": 100,
            },
            {
                "game_id": "2",
                "game_date": "2024-10-04",
                "season": "2024-25",
                "home_team": "Heat",
                "away_team": "Celtics",
                "home_points": 95,
                "away_points": 105,
            },
            {
                "game_id": "3",
                "game_date": "2024-10-06",
                "season": "2024-25",
                "home_team": "Celtics",
                "away_team": "Heat",
                "home_points": 120,
                "away_points": 90,
            },
        ]
    )


def test_engineer_features_has_required_schema():
    raw = _raw_games()
    games = engineer_features(raw)
    assert REQUIRED_COLUMNS.issubset(games.columns)
    assert "home_win" in games.columns
    assert len(games) == 3
    assert list(games["home_win"]) == [1, 0, 1]


def test_first_game_of_a_team_uses_default_values_not_future_data():
    raw = _raw_games()
    games = engineer_features(raw)

    first_game = games.iloc[0]
    assert first_game["home_team"] == "Celtics"
    # Primeiro jogo do Celtics: não pode usar o resultado dos jogos seguintes.
    assert first_game["home_last10_win_pct"] == 0.5
    assert first_game["home_rest_days"] == 3
    assert first_game["home_off_rating"] == DEFAULT_RATING
    assert first_game["home_def_rating"] == DEFAULT_RATING


def test_future_results_do_not_change_earlier_engineered_features():
    raw = _raw_games()
    initial = engineer_features(raw)
    future = raw.tail(1).assign(game_id="future", game_date="2026-01-01",
                               home_points=500, away_points=400)
    extended = engineer_features(pd.concat([raw, future], ignore_index=True))
    pd.testing.assert_frame_equal(initial, extended.head(len(initial)))


def test_recent_points_use_prior_games_in_both_locations_and_exclude_same_day():
    raw = _raw_games()
    same_day = raw.tail(1).assign(game_id="same-day", home_points=900, away_points=800)
    games = pd.concat([raw, same_day], ignore_index=True).iloc[[3, 1, 0, 2]]
    averages = pregame_scoring_averages(games)
    assert averages.index.equals(games.index)
    assert averages.loc[0, "home_points_avg10"] == DEFAULT_RATING
    assert averages.loc[1, "away_points_avg10"] == 110
    assert averages.loc[2, "home_points_avg10"] == pytest.approx(107.5)
    assert averages.loc[3, "home_points_avg10"] == pytest.approx(107.5)
    assert averages.loc[3, "away_points_avg10"] == 95


def test_rest_days_matches_real_gap_between_games():
    raw = _raw_games()
    games = engineer_features(raw).sort_values("game_date").reset_index(drop=True)

    third_game = games.iloc[2]
    assert third_game["home_team"] == "Celtics"
    # Celtics jogou em 2024-10-04 (fora) e depois em 2024-10-06 (casa): 2 dias de descanso.
    assert third_game["home_rest_days"] == 2


def test_official_rating_is_used_instead_of_points_when_available():
    raw = _raw_games()
    # Rating oficiais só para os dois primeiros jogos do Celtics, deliberadamente
    # diferentes dos pontos marcados/sofridos (110/100 e 105/95).
    advanced_stats = pd.DataFrame(
        [
            {
                "game_id": "1",
                "team": "Celtics",
                "off_rating": 130.0,
                "def_rating": 90.0,
                "net_rating": 40.0,
                "pace": 100.0,
            },
            {
                "game_id": "2",
                "team": "Celtics",
                "off_rating": 140.0,
                "def_rating": 95.0,
                "net_rating": 45.0,
                "pace": 100.0,
            },
        ]
    )

    games = engineer_features(raw, advanced_stats).sort_values("game_date").reset_index(drop=True)
    third_game = games.iloc[2]

    assert third_game["home_team"] == "Celtics"
    assert third_game["home_off_rating"] == pytest.approx((130.0 + 140.0) / 2)
    assert third_game["home_def_rating"] == pytest.approx((90.0 + 95.0) / 2)
    snapshot = team_snapshot(games.head(2), "Celtics")
    assert snapshot["off_rating"] == pytest.approx(third_game["home_off_rating"])
    assert snapshot["def_rating"] == pytest.approx(third_game["home_def_rating"])
    assert snapshot["points_for"] == pytest.approx(107.5)


def test_without_advanced_stats_falls_back_to_points_like_before():
    raw = _raw_games()
    with_advanced = engineer_features(raw, advanced_stats=None)
    without_arg = engineer_features(raw)
    pd.testing.assert_frame_equal(with_advanced, without_arg)
