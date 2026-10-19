import pandas as pd

from src.shot_connector import SHOT_COLUMNS, normalize_shot_chart


def _raw_shot_chart() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "GAME_ID": "0022300001",
                "GAME_EVENT_ID": 12,
                "PLAYER_ID": 201,
                "PLAYER_NAME": "Jayson Tatum",
                "TEAM_ID": 1610612738,
                "TEAM_NAME": "Boston Celtics",
                "PERIOD": 1,
                "MINUTES_REMAINING": 10,
                "SECONDS_REMAINING": 45,
                "EVENT_TYPE": "Made Shot",
                "ACTION_TYPE": "Jump Shot",
                "SHOT_TYPE": "3PT Field Goal",
                "SHOT_ZONE_BASIC": "Above the Break 3",
                "SHOT_ZONE_AREA": "Center(C)",
                "SHOT_ZONE_RANGE": "24+ ft.",
                "SHOT_DISTANCE": 26,
                "LOC_X": 10,
                "LOC_Y": 260,
                "SHOT_ATTEMPTED_FLAG": 1,
                "SHOT_MADE_FLAG": 1,
                "GAME_DATE": "20241015",
                "HTM": "BOS",
                "VTM": "NYK",
            },
            {
                "GAME_ID": "0022300001",
                "GAME_EVENT_ID": 45,
                "PLAYER_ID": 201,
                "PLAYER_NAME": "Jayson Tatum",
                "TEAM_ID": 1610612738,
                "TEAM_NAME": "Boston Celtics",
                "PERIOD": 2,
                "MINUTES_REMAINING": 3,
                "SECONDS_REMAINING": 12,
                "EVENT_TYPE": "Missed Shot",
                "ACTION_TYPE": "Layup Shot",
                "SHOT_TYPE": "2PT Field Goal",
                "SHOT_ZONE_BASIC": "Restricted Area",
                "SHOT_ZONE_AREA": "Center(C)",
                "SHOT_ZONE_RANGE": "Less Than 8 ft.",
                "SHOT_DISTANCE": 1,
                "LOC_X": -5,
                "LOC_Y": 8,
                "SHOT_ATTEMPTED_FLAG": 1,
                "SHOT_MADE_FLAG": 0,
                "GAME_DATE": "20241015",
                "HTM": "BOS",
                "VTM": "NYK",
            },
        ]
    )


def test_normalize_shot_chart_returns_expected_columns():
    normalized = normalize_shot_chart(_raw_shot_chart(), season="2024-25")
    assert list(normalized.columns) == SHOT_COLUMNS
    assert len(normalized) == 2
    assert (normalized["season"] == "2024-25").all()


def test_normalize_shot_chart_converts_loc_to_feet():
    normalized = normalize_shot_chart(_raw_shot_chart(), season="2024-25")
    assert normalized.loc[0, "loc_x_ft"] == 1.0
    assert normalized.loc[0, "loc_y_ft"] == 26.0


def test_normalize_shot_chart_derives_opponent_for_home_shooter():
    normalized = normalize_shot_chart(_raw_shot_chart(), season="2024-25")
    # TEAM_NAME (Boston Celtics) == HTM (BOS) => jogador é o mandante, adversário é o visitante.
    assert (normalized["opponent"] == "New York Knicks").all()


def test_normalize_shot_chart_derives_opponent_for_away_shooter():
    raw = _raw_shot_chart()
    raw["TEAM_NAME"] = "New York Knicks"
    raw["TEAM_ID"] = 1610612752

    normalized = normalize_shot_chart(raw, season="2024-25")
    assert (normalized["opponent"] == "Boston Celtics").all()


def test_normalize_shot_chart_parses_game_date():
    normalized = normalize_shot_chart(_raw_shot_chart(), season="2024-25")
    assert pd.api.types.is_datetime64_any_dtype(normalized["game_date"])
    assert normalized.loc[0, "game_date"] == pd.Timestamp("2024-10-15")
