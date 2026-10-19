import pandas as pd

from src.store import (
    log_model_training,
    log_player_prediction,
    log_team_prediction,
    read_model_training_log,
    read_player_predictions,
    read_team_predictions,
    resolve_player_predictions,
    resolve_team_predictions,
)


def test_log_and_read_team_prediction(tmp_path):
    db_path = tmp_path / "nba.db"
    prediction_id = log_team_prediction(
        "Boston Celtics", "New York Knicks", 0.64, 116.0, 111.0, "Média", db_path
    )
    assert prediction_id == 1

    predictions = read_team_predictions(db_path)
    assert len(predictions) == 1
    row = predictions.iloc[0]
    assert row["home_team"] == "Boston Celtics"
    assert row["away_team"] == "New York Knicks"
    assert row["home_win_probability"] == 0.64
    assert pd.isna(row["resolved_at"])


def test_resolve_team_predictions_matches_future_game_not_past(tmp_path):
    db_path = tmp_path / "nba.db"
    log_team_prediction("Boston Celtics", "New York Knicks", 0.64, 116.0, 111.0, "Média", db_path)

    # Um jogo antes do registro (não deve casar) e um depois (deve casar).
    games = pd.DataFrame(
        [
            {
                "home_team": "Boston Celtics",
                "away_team": "New York Knicks",
                "game_date": pd.Timestamp("2000-01-01"),
                "home_points": 100,
                "away_points": 90,
            },
            {
                "home_team": "Boston Celtics",
                "away_team": "New York Knicks",
                "game_date": pd.Timestamp("2030-01-01"),
                "home_points": 120,
                "away_points": 108,
            },
        ]
    )

    resolved_count = resolve_team_predictions(games, db_path)
    assert resolved_count == 1

    predictions = read_team_predictions(db_path)
    row = predictions.iloc[0]
    assert row["actual_home_score"] == 120
    assert row["actual_away_score"] == 108
    assert pd.notna(row["resolved_at"])


def test_resolve_team_predictions_leaves_unmatched_pending(tmp_path):
    db_path = tmp_path / "nba.db"
    log_team_prediction("Miami Heat", "Orlando Magic", 0.55, 110.0, 105.0, "Baixa", db_path)

    games = pd.DataFrame(
        [
            {
                "home_team": "Boston Celtics",
                "away_team": "New York Knicks",
                "game_date": pd.Timestamp("2030-01-01"),
                "home_points": 120,
                "away_points": 108,
            }
        ]
    )

    resolved_count = resolve_team_predictions(games, db_path)
    assert resolved_count == 0

    predictions = read_team_predictions(db_path)
    assert pd.isna(predictions.iloc[0]["resolved_at"])


def test_log_and_read_player_prediction(tmp_path):
    db_path = tmp_path / "nba.db"
    prediction_id = log_player_prediction(
        1, "A One", "Boston Celtics", True, 32.0, 25.4, 6.1, 4.8, "Média", db_path
    )
    assert prediction_id == 1

    predictions = read_player_predictions(db_path)
    assert len(predictions) == 1
    row = predictions.iloc[0]
    assert row["player_id"] == 1
    assert row["player_name"] == "A One"
    assert row["opponent"] == "Boston Celtics"
    assert bool(row["is_home"]) is True
    assert row["predicted_pts"] == 25.4
    assert pd.isna(row["resolved_at"])


def test_resolve_player_predictions_matches_next_real_game_not_past(tmp_path):
    db_path = tmp_path / "nba.db"
    log_player_prediction(1, "A One", "Boston Celtics", True, 32.0, 25.4, 6.1, 4.8, "Média", db_path)

    # Um jogo antes do registro (não deve casar) e um depois (deve casar),
    # mesmo que o adversário real não seja o que foi escolhido na previsão —
    # a resolução casa só por player_id + data.
    player_games = pd.DataFrame(
        [
            {
                "player_id": 1,
                "game_date": pd.Timestamp("2000-01-01"),
                "minutes": 20.0,
                "pts": 10,
                "reb": 3,
                "ast": 2,
            },
            {
                "player_id": 1,
                "game_date": pd.Timestamp("2030-01-01"),
                "minutes": 34.0,
                "pts": 28,
                "reb": 7,
                "ast": 5,
            },
        ]
    )

    resolved_count = resolve_player_predictions(player_games, db_path)
    assert resolved_count == 1

    predictions = read_player_predictions(db_path)
    row = predictions.iloc[0]
    assert row["actual_minutes"] == 34.0
    assert row["actual_pts"] == 28
    assert row["actual_reb"] == 7
    assert row["actual_ast"] == 5
    assert pd.notna(row["resolved_at"])


def test_resolve_player_predictions_leaves_unmatched_pending(tmp_path):
    db_path = tmp_path / "nba.db"
    log_player_prediction(1, "A One", "Boston Celtics", True, 32.0, 25.4, 6.1, 4.8, "Média", db_path)

    # Jogo de outro jogador (player_id diferente) não deve casar.
    player_games = pd.DataFrame(
        [
            {
                "player_id": 2,
                "game_date": pd.Timestamp("2030-01-01"),
                "minutes": 30.0,
                "pts": 20,
                "reb": 5,
                "ast": 4,
            }
        ]
    )

    resolved_count = resolve_player_predictions(player_games, db_path)
    assert resolved_count == 0

    predictions = read_player_predictions(db_path)
    assert pd.isna(predictions.iloc[0]["resolved_at"])


def test_log_and_read_model_training_log(tmp_path):
    db_path = tmp_path / "nba.db"
    metrics = {"accuracy": 0.62, "log_loss": 0.65, "brier_score": 0.21}
    log_model_training("team", 9509, metrics, db_path)

    log = read_model_training_log(db_path)
    assert len(log) == 1
    row = log.iloc[0]
    assert row["model_type"] == "team"
    assert row["n_games"] == 9509
    assert row["metrics"] == metrics
