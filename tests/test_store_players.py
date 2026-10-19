import pandas as pd

from src.store import (
    count_distinct_players,
    count_player_games,
    games_missing_starter_status,
    read_player_games,
    update_starter_status,
    upsert_player_games,
)


def _sample_player_games() -> pd.DataFrame:
    base = {
        "game_id": "G1",
        "game_date": "2024-01-10",
        "season": "2023-24",
        "opponent": "B",
        "is_home": True,
        "minutes": 30,
        "pts": 22,
        "oreb": 1,
        "dreb": 4,
        "reb": 5,
        "ast": 5,
        "stl": 1,
        "blk": 0,
        "tov": 2,
        "pf": 2,
        "fgm": 8,
        "fga": 15,
        "fg3m": 2,
        "fg3a": 5,
        "ftm": 4,
        "fta": 5,
    }
    return pd.DataFrame(
        [
            {**base, "player_id": 1, "player_name": "A One", "team": "A"},
            {**base, "player_id": 2, "player_name": "A Two", "team": "A", "pts": 8},
        ]
    )


def test_upsert_player_games_inserts_new_rows(tmp_path):
    db_path = tmp_path / "nba.db"
    added = upsert_player_games(_sample_player_games(), db_path)
    assert added == 2
    assert count_player_games(db_path) == 2


def test_upsert_player_games_does_not_duplicate_on_rerun(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)
    added_again = upsert_player_games(_sample_player_games(), db_path)

    assert added_again == 0
    assert count_player_games(db_path) == 2


def test_count_distinct_players_counts_unique_player_ids(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)
    assert count_distinct_players(db_path) == 2


def test_count_distinct_players_returns_zero_when_db_missing(tmp_path):
    db_path = tmp_path / "does_not_exist.db"
    assert count_distinct_players(db_path) == 0


def test_read_player_games_returns_expected_schema(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)

    data = read_player_games(db_path)
    assert set(data["player_id"]) == {1, 2}
    assert pd.api.types.is_datetime64_any_dtype(data["game_date"])
    assert data["is_home"].dtype == bool


def test_new_player_games_have_no_starter_status_until_collected(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)

    assert games_missing_starter_status(db_path) == ["G1"]


def test_update_starter_status_fills_in_titles_and_clears_missing_list(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)

    starters = pd.DataFrame(
        [
            {"game_id": "G1", "player_id": 1, "is_starter": True},
            {"game_id": "G1", "player_id": 2, "is_starter": False},
        ]
    )
    updated = update_starter_status(starters, db_path)
    assert updated == 2
    assert games_missing_starter_status(db_path) == []

    data = read_player_games(db_path)
    player_one = data[data["player_id"] == 1].iloc[0]
    player_two = data[data["player_id"] == 2].iloc[0]
    assert bool(player_one["is_starter"]) is True
    assert bool(player_two["is_starter"]) is False


def test_update_starter_status_does_not_insert_unknown_players(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)

    # player_id 99 nunca teve boxscore coletado — não deve criar linha nova.
    unknown = pd.DataFrame([{"game_id": "G1", "player_id": 99, "is_starter": True}])
    updated = update_starter_status(unknown, db_path)

    assert updated == 0
    assert count_player_games(db_path) == 2
