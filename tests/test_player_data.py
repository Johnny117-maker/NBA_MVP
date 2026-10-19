import pandas as pd

from src.player_data import generate_demo_player_games, load_player_games


def test_generate_demo_player_games_has_valid_schema():
    games = generate_demo_player_games(games_per_team=5)

    required = {
        "game_id",
        "game_date",
        "season",
        "player_id",
        "player_name",
        "team",
        "opponent",
        "is_home",
        "minutes",
        "pts",
        "fgm",
        "fga",
        "fg3m",
        "fg3a",
        "ftm",
        "fta",
    }
    assert required.issubset(games.columns)
    assert pd.api.types.is_datetime64_any_dtype(games["game_date"])
    assert (games["minutes"] >= 0).all()
    assert (games["fga"] >= games["fgm"]).all()
    assert (games["fga"] >= games["fg3a"]).all()


def test_generate_demo_player_games_is_deterministic_with_seed():
    first = generate_demo_player_games(games_per_team=3, seed=11)
    second = generate_demo_player_games(games_per_team=3, seed=11)
    pd.testing.assert_frame_equal(first, second)


def test_load_player_games_demo_adds_efficiency_and_per36():
    games = load_player_games(source="demo")
    assert "true_shooting_pct" in games.columns
    assert "usage_pct" in games.columns
    assert "pts_per36" in games.columns
