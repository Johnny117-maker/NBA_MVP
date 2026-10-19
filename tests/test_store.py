import sqlite3

import pandas as pd

from src.store import count_distinct_teams, count_games, init_db, read_raw_games, upsert_games


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


def test_upsert_games_inserts_new_rows(tmp_path):
    db_path = tmp_path / "nba.db"
    added = upsert_games(_sample_games(), db_path)
    assert added == 2
    assert count_games(db_path) == 2


def test_upsert_games_does_not_duplicate_on_rerun(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_games(_sample_games(), db_path)
    added_again = upsert_games(_sample_games(), db_path)

    assert added_again == 0
    assert count_games(db_path) == 2


def test_count_distinct_teams_counts_unique_home_and_away_teams(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_games(_sample_games(), db_path)
    # _sample_games: (Celtics x Knicks), (Heat x Celtics) -> 3 times distintos.
    assert count_distinct_teams(db_path) == 3


def test_count_distinct_teams_returns_zero_when_db_missing(tmp_path):
    db_path = tmp_path / "does_not_exist.db"
    assert count_distinct_teams(db_path) == 0


def test_read_raw_games_returns_expected_schema_sorted_by_date(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_games(_sample_games(), db_path)

    data = read_raw_games(db_path)
    assert list(data["game_id"]) == ["1", "2"]
    assert pd.api.types.is_datetime64_any_dtype(data["game_date"])
    assert set(data.columns) == {
        "game_id",
        "game_date",
        "season",
        "home_team",
        "away_team",
        "home_points",
        "away_points",
    }


def test_init_db_adds_is_starter_column_to_a_pre_existing_database(tmp_path):
    """Bancos coletados antes da coluna `is_starter` existir (Fase 5) precisam
    ganhá-la via ALTER TABLE, sem perder as linhas já coletadas."""
    db_path = tmp_path / "nba.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE player_game_stats (
                game_id TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                game_date TEXT NOT NULL,
                season TEXT NOT NULL,
                player_name TEXT NOT NULL,
                team TEXT NOT NULL,
                opponent TEXT NOT NULL,
                is_home INTEGER NOT NULL,
                minutes REAL NOT NULL,
                pts INTEGER NOT NULL,
                oreb INTEGER NOT NULL,
                dreb INTEGER NOT NULL,
                reb INTEGER NOT NULL,
                ast INTEGER NOT NULL,
                stl INTEGER NOT NULL,
                blk INTEGER NOT NULL,
                tov INTEGER NOT NULL,
                pf INTEGER NOT NULL,
                fgm INTEGER NOT NULL,
                fga INTEGER NOT NULL,
                fg3m INTEGER NOT NULL,
                fg3a INTEGER NOT NULL,
                ftm INTEGER NOT NULL,
                fta INTEGER NOT NULL,
                PRIMARY KEY (game_id, player_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO player_game_stats VALUES
            ('G1', 1, '2024-01-10', '2023-24', 'A One', 'A', 'B', 1,
             30, 22, 1, 4, 5, 5, 1, 0, 2, 2, 8, 15, 2, 5, 4, 5)
            """
        )
        connection.commit()

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(player_game_stats)")}
        assert "is_starter" in columns
        row = connection.execute(
            "SELECT is_starter FROM player_game_stats WHERE game_id = 'G1'"
        ).fetchone()
        assert row == (None,)  # coluna nova, linha antiga continua sem o dado
