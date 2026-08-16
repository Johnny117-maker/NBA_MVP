import pandas as pd

from src.shot_storage import (
    ZONE_REFERENCE_COLUMNS,
    count_player_shots,
    list_players_with_shots,
    players_missing_shots,
    read_player_shots,
    read_shots_for_zone_reference,
    upsert_player_shots,
)
from src.store import upsert_player_games


def _sample_shots(game_event_id: int = 12) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": 201,
                "player_name": "Jayson Tatum",
                "game_id": "0022300001",
                "game_event_id": game_event_id,
                "season": "2024-25",
                "game_date": "2024-10-15",
                "team_id": 1610612738,
                "team_name": "Boston Celtics",
                "opponent": "New York Knicks",
                "period": 1,
                "minutes_remaining": 10,
                "seconds_remaining": 45,
                "event_type": "Made Shot",
                "action_type": "Jump Shot",
                "shot_type": "3PT Field Goal",
                "shot_zone_basic": "Above the Break 3",
                "shot_zone_area": "Center(C)",
                "shot_zone_range": "24+ ft.",
                "shot_distance": 26,
                "loc_x": 10,
                "loc_y": 260,
                "loc_x_ft": 1.0,
                "loc_y_ft": 26.0,
                "shot_attempted": 1,
                "shot_made": 1,
                "source": "nba_api",
            }
        ]
    )


def _sample_player_games() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_id": "0022300001",
                "player_id": 201,
                "game_date": "2024-10-15",
                "season": "2024-25",
                "player_name": "Jayson Tatum",
                "team": "BOS",
                "opponent": "NYK",
                "is_home": True,
                "minutes": 34.0,
                "pts": 28,
                "oreb": 1,
                "dreb": 6,
                "reb": 7,
                "ast": 4,
                "stl": 1,
                "blk": 0,
                "tov": 2,
                "pf": 2,
                "fgm": 10,
                "fga": 20,
                "fg3m": 4,
                "fg3a": 10,
                "ftm": 4,
                "fta": 4,
            },
            {
                "game_id": "0022300002",
                "player_id": 202,
                "game_date": "2024-10-16",
                "season": "2024-25",
                "player_name": "Jalen Brunson",
                "team": "NYK",
                "opponent": "BOS",
                "is_home": False,
                "minutes": 32.0,
                "pts": 25,
                "oreb": 0,
                "dreb": 3,
                "reb": 3,
                "ast": 6,
                "stl": 1,
                "blk": 0,
                "tov": 1,
                "pf": 3,
                "fgm": 9,
                "fga": 18,
                "fg3m": 2,
                "fg3a": 6,
                "ftm": 5,
                "fta": 5,
            },
        ]
    )


def test_upsert_player_shots_inserts_new_rows(tmp_path):
    db_path = tmp_path / "nba.db"
    added = upsert_player_shots(_sample_shots(), db_path)
    assert added == 1
    assert count_player_shots(db_path) == 1


def test_upsert_player_shots_does_not_duplicate_on_rerun(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_shots(_sample_shots(), db_path)
    added_again = upsert_player_shots(_sample_shots(), db_path)

    assert added_again == 0
    assert count_player_shots(db_path) == 1


def test_upsert_player_shots_allows_same_player_different_event(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_shots(_sample_shots(game_event_id=12), db_path)
    added = upsert_player_shots(_sample_shots(game_event_id=45), db_path)

    assert added == 1
    assert count_player_shots(db_path) == 2


def test_read_player_shots_filters_by_player_and_season(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_shots(_sample_shots(), db_path)

    data = read_player_shots(db_path, player_id=201, season="2024-25")
    assert len(data) == 1
    assert pd.api.types.is_datetime64_any_dtype(data["game_date"])
    assert bool(data.loc[0, "shot_made"]) is True

    empty = read_player_shots(db_path, player_id=999)
    assert empty.empty


def test_read_player_shots_returns_empty_frame_when_db_missing(tmp_path):
    db_path = tmp_path / "does_not_exist.db"
    data = read_player_shots(db_path)
    assert data.empty


def _second_player_shot() -> pd.DataFrame:
    shot = _sample_shots().iloc[0].to_dict()
    shot.update(
        player_id=202,
        player_name="Jalen Brunson",
        team_name="New York Knicks",
        opponent="Boston Celtics",
        game_event_id=1,
    )
    return pd.DataFrame([shot])


def test_read_shots_for_zone_reference_returns_only_reference_columns(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_shots(_sample_shots(), db_path)
    upsert_player_shots(_second_player_shot(), db_path)

    data = read_shots_for_zone_reference(db_path)
    assert set(data.columns) == set(ZONE_REFERENCE_COLUMNS)
    assert "loc_x" not in data.columns
    assert "action_type" not in data.columns
    assert len(data) == 2
    assert pd.api.types.is_datetime64_any_dtype(data["game_date"])
    assert data["shot_made"].dtype == bool


def test_read_shots_for_zone_reference_returns_empty_frame_when_db_missing(tmp_path):
    db_path = tmp_path / "does_not_exist.db"
    data = read_shots_for_zone_reference(db_path)
    assert data.empty
    assert set(data.columns) == set(ZONE_REFERENCE_COLUMNS)


def test_list_players_with_shots_returns_distinct_players_sorted_by_name(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_shots(_sample_shots(), db_path)
    upsert_player_shots(_second_player_shot(), db_path)

    players = list_players_with_shots(db_path)
    assert list(players["player_name"]) == ["Jalen Brunson", "Jayson Tatum"]
    assert set(players["player_id"]) == {201, 202}


def test_list_players_with_shots_returns_empty_frame_when_db_missing(tmp_path):
    db_path = tmp_path / "does_not_exist.db"
    players = list_players_with_shots(db_path)
    assert players.empty
    assert list(players.columns) == ["player_id", "player_name"]


def test_players_missing_shots_lists_only_uncovered_player_seasons(tmp_path):
    db_path = tmp_path / "nba.db"
    upsert_player_games(_sample_player_games(), db_path)
    upsert_player_shots(_sample_shots(), db_path)

    missing = players_missing_shots(db_path)
    assert missing == [(202, "Jalen Brunson", "2024-25")]


def test_players_missing_shots_returns_empty_without_player_game_stats(tmp_path):
    db_path = tmp_path / "nba.db"
    missing = players_missing_shots(db_path)
    assert missing == []
