import pandas as pd

from src.store import (
    count_team_advanced_stats,
    games_missing_advanced_stats,
    read_team_advanced_stats,
    upsert_games,
    upsert_team_advanced_stats,
)


def _sample_games() -> pd.DataFrame:
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
        ]
    )


def _sample_advanced_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_id": "1",
                "team": "Celtics",
                "off_rating": 118.0,
                "def_rating": 108.0,
                "net_rating": 10.0,
                "pace": 99.0,
            },
            {
                "game_id": "1",
                "team": "Knicks",
                "off_rating": 108.0,
                "def_rating": 118.0,
                "net_rating": -10.0,
                "pace": 99.0,
            },
        ]
    )


def test_upsert_team_advanced_stats_inserts_new_rows(tmp_path):
    db_path = tmp_path / "nba.db"
    added = upsert_team_advanced_stats(_sample_advanced_stats(), db_path)
    assert added == 2
    assert count_team_advanced_stats(db_path) == 2


def test_upsert_team_advanced_stats_does_not_duplicate_on_rerun(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_team_advanced_stats(_sample_advanced_stats(), db_path)
    added_again = upsert_team_advanced_stats(_sample_advanced_stats(), db_path)

    assert added_again == 0
    assert count_team_advanced_stats(db_path) == 2


def test_read_team_advanced_stats_returns_expected_schema(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_team_advanced_stats(_sample_advanced_stats(), db_path)

    data = read_team_advanced_stats(db_path)
    assert set(data["team"]) == {"Celtics", "Knicks"}
    assert set(data.columns) == {"game_id", "team", "off_rating", "def_rating", "net_rating", "pace"}


def test_games_missing_advanced_stats_lists_only_uncovered_games(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_games(_sample_games(), db_path)
    upsert_team_advanced_stats(_sample_advanced_stats(), db_path)

    missing = games_missing_advanced_stats(db_path)
    assert missing == ["2"]
