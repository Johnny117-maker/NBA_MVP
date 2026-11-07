from scripts import retrain_models
from src.data import generate_demo_games


def test_team_only_records_team_metrics_without_training_other_models(monkeypatch):
    games = generate_demo_games(100)
    records = []
    monkeypatch.setattr(retrain_models, "_load_team_games", lambda: (games, "demo"))
    monkeypatch.setattr(retrain_models, "log_model_training", lambda *args: records.append(args))

    def unexpected_player_training():
        raise AssertionError("--team-only não deve carregar jogadores")

    monkeypatch.setattr(retrain_models, "_load_player_games", unexpected_player_training)
    retrain_models.main(["--team-only"])
    assert len(records) == 1
    assert records[0][0:2] == ("team", 100)
    assert records[0][2]["score_model_version"] == 3
