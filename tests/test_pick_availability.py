import pandas as pd
import pytest

from src.injuries import current_pick_players, filter_pick_players
from src.live_store import set_state
from src.today_picks import round_highlights


@pytest.mark.parametrize(
    "status",
    [
        "Fora",
        "Reserva por lesão",
        "Dia a dia",
        "Questionável",
        "Improvável",
        "Provável",
        "Suspenso",
        "Não classificado",
    ],
)
def test_injury_or_uncertainty_removes_player_using_full_normalized_name(status):
    players = pd.DataFrame(
        [
            {"player_id": 1, "player_name": "José Teste", "team": "BOS"},
            {"player_id": 100, "player_name": "Outro Jogador", "team": "BOS"},
        ]
    )
    injury = pd.DataFrame([{"athlete_id": "100", "player": "Jose Teste", "team": "NYK", "status": status}])
    result = filter_pick_players(players, injury)
    # Também cobre transferência ainda ausente no histórico. ESPN ID não é NBA ID.
    assert result.player_id.tolist() == [100]
    assert len(players) == 2


def test_available_status_and_explicit_empty_bulletin_allow_selection(tmp_path):
    players = pd.DataFrame([{"player_id": 1, "player_name": "Atleta Teste"}])
    injury = pd.DataFrame([{"player": "Atleta Teste", "team": "BOS", "status": "Disponível"}])
    assert len(filter_pick_players(players, injury)) == 1
    path = tmp_path / "nba.db"
    assert current_pick_players(path, players).empty
    set_state(path, "injury_snapshot", {"source": "ESPN", "rows": []})
    assert len(current_pick_players(path, players)) == 1


def test_filtering_before_ranking_selects_next_eligible_player():
    form = pd.DataFrame(
        [
            {"player_id": 1, "player_name": "Estrela", "team": "BOS", "impact_recent": 40},
            {"player_id": 2, "player_name": "Substituto", "team": "BOS", "impact_recent": 30},
            {"player_id": 3, "player_name": "J. Estrela", "team": "NYK", "impact_recent": 25},
        ]
    )
    injuries = pd.DataFrame([{"player": "Estrela", "team": "BOS", "status": "Fora"}])
    game = {
        "game_id": "g1",
        "game_status": 1,
        "home_team_tricode": "BOS",
        "away_team_tricode": "NYK",
        "home_team_name": "Boston Celtics",
        "away_team_name": "New York Knicks",
    }
    result = round_highlights(filter_pick_players(form, injuries), pd.DataFrame([game]), top_n=1)
    assert result.player_id.tolist() == [2, 3]
