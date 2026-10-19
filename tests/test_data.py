import pandas as pd

from src.data import DEMO_TEAMS, REQUIRED_COLUMNS, available_teams, generate_demo_games, team_snapshot
from src.nba_teams import TEAM_CONFERENCE


def test_demo_games_have_required_schema():
    games = generate_demo_games(number_of_games=120)
    assert REQUIRED_COLUMNS.issubset(games.columns)
    assert "home_win" in games.columns
    assert len(games) == 120
    assert pd.api.types.is_datetime64_any_dtype(games["game_date"])


def test_team_snapshot_is_valid():
    games = generate_demo_games(number_of_games=180)
    team = available_teams(games)[0]
    snapshot = team_snapshot(games, team)
    assert 0 <= snapshot["win_pct"] <= 1
    assert snapshot["games"] <= 10
    assert snapshot["off_rating"] > 0


def test_demo_teams_covers_all_30_real_teams():
    assert len(DEMO_TEAMS) == 30
    assert set(DEMO_TEAMS) == set(TEAM_CONFERENCE)

