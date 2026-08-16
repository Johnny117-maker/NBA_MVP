import numpy as np
import pandas as pd
import pytest

from src.data import generate_demo_games
from src.model import train_models
from src.season_simulator import (
    current_standings,
    simulate_play_in,
    simulate_remaining_wins,
    simulate_season,
    split_season,
    team_snapshots,
)

# Dez times reais do Leste (bate com src.nba_teams.TEAM_CONFERENCE), com força
# decrescente para permitir verificações determinísticas de classificação.
TEAMS = [
    "Boston Celtics",
    "New York Knicks",
    "Milwaukee Bucks",
    "Philadelphia 76ers",
    "Cleveland Cavaliers",
    "Miami Heat",
    "Indiana Pacers",
    "Orlando Magic",
    "Atlanta Hawks",
    "Chicago Bulls",
]
# Time 0 é o mais forte, time 9 o mais fraco.
OFF_RATING = {team: 118.0 - i for i, team in enumerate(TEAMS)}
DEF_RATING = {team: 105.0 + i for i, team in enumerate(TEAMS)}
WIN_PCT = {team: max(0.1, 0.85 - 0.07 * i) for i, team in enumerate(TEAMS)}


def _team_row(team: str, opponent: str, is_home: bool) -> dict:
    prefix_self = "home" if is_home else "away"
    prefix_opp = "away" if is_home else "home"
    return {
        f"{prefix_self}_off_rating": OFF_RATING[team],
        f"{prefix_self}_def_rating": DEF_RATING[team],
        f"{prefix_self}_net_rating": OFF_RATING[team] - DEF_RATING[team],
        f"{prefix_self}_last10_win_pct": WIN_PCT[team],
        f"{prefix_self}_rest_days": 2,
        f"{prefix_opp}_off_rating": OFF_RATING[opponent],
        f"{prefix_opp}_def_rating": DEF_RATING[opponent],
        f"{prefix_opp}_net_rating": OFF_RATING[opponent] - DEF_RATING[opponent],
        f"{prefix_opp}_last10_win_pct": WIN_PCT[opponent],
        f"{prefix_opp}_rest_days": 2,
    }


def _make_game(game_id, game_date, home, away, home_win) -> dict:
    row = {
        "game_id": game_id,
        "game_date": pd.Timestamp(game_date),
        "season": "TEST-SEASON",
        "home_team": home,
        "away_team": away,
        "home_points": 110 if home_win else 100,
        "away_points": 100 if home_win else 110,
        "home_win": int(home_win),
    }
    row.update(_team_row(home, away, is_home=True))
    row.update(_team_row(away, home, is_home=False))
    return row


def _fabricated_season() -> pd.DataFrame:
    rows = []
    game_id = 0
    # Jogos conhecidos: time mais forte (índice menor) sempre vence o mais fraco.
    for i, home in enumerate(TEAMS):
        for j, away in enumerate(TEAMS):
            if home == away:
                continue
            home_win = i < j
            rows.append(_make_game(f"K{game_id}", "2024-01-01", home, away, home_win))
            game_id += 1

    # Jogos restantes (depois do corte): resultado real irrelevante, o simulador ignora.
    remaining_pairs = [
        (TEAMS[0], TEAMS[9]),
        (TEAMS[1], TEAMS[8]),
        (TEAMS[2], TEAMS[7]),
        (TEAMS[3], TEAMS[6]),
        (TEAMS[4], TEAMS[5]),
        (TEAMS[9], TEAMS[0]),
        (TEAMS[8], TEAMS[1]),
    ]
    for home, away in remaining_pairs:
        rows.append(_make_game(f"R{game_id}", "2024-03-01", home, away, True))
        game_id += 1

    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def bundle():
    return train_models(generate_demo_games(number_of_games=220))


@pytest.fixture(scope="module")
def season_games():
    return _fabricated_season()


def test_split_season_separates_known_and_remaining(season_games):
    known, remaining = split_season(season_games, "TEST-SEASON", "2024-02-01")
    assert (known["game_date"] < pd.Timestamp("2024-02-01")).all()
    assert (remaining["game_date"] >= pd.Timestamp("2024-02-01")).all()
    assert len(known) + len(remaining) == len(season_games)


def test_current_standings_matches_manual_count(season_games):
    known, _ = split_season(season_games, "TEST-SEASON", "2024-02-01")
    standings = current_standings(known).set_index("team")

    # Cada time joga contra os outros 9 uma vez em casa e uma vez fora (18 jogos).
    # O time mais forte (índice 0) venceu todos eles.
    assert standings.loc[TEAMS[0], "wins"] == 18
    assert standings.loc[TEAMS[0], "losses"] == 0
    # O time mais fraco (índice 9) perdeu todos os 18 jogos conhecidos.
    assert standings.loc[TEAMS[9], "wins"] == 0
    assert standings.loc[TEAMS[9], "losses"] == 18


def test_simulate_remaining_wins_favors_stronger_team(season_games, bundle):
    known, remaining = split_season(season_games, "TEST-SEASON", "2024-02-01")
    standings = current_standings(known).set_index("team")
    snapshots = team_snapshots(known, TEAMS)

    from src.season_simulator import remaining_game_probabilities

    probabilities = remaining_game_probabilities(bundle, snapshots, remaining)
    final_wins = simulate_remaining_wins(
        remaining, probabilities, standings["wins"], TEAMS, n_simulations=2000, seed=1
    )

    assert final_wins.shape == (2000, len(TEAMS))
    strongest_mean = final_wins[:, TEAMS.index(TEAMS[0])].mean()
    weakest_mean = final_wins[:, TEAMS.index(TEAMS[9])].mean()
    assert strongest_mean > weakest_mean


def test_simulate_play_in_never_contradicts_itself(season_games, bundle):
    known, remaining = split_season(season_games, "TEST-SEASON", "2024-02-01")
    standings = current_standings(known).set_index("team")
    snapshots = team_snapshots(known, TEAMS)

    from src.season_simulator import remaining_game_probabilities

    probabilities = remaining_game_probabilities(bundle, snapshots, remaining)
    final_wins = simulate_remaining_wins(
        remaining, probabilities, standings["wins"], TEAMS, n_simulations=500, seed=2
    )
    result = simulate_play_in(final_wins, TEAMS, snapshots, bundle, seed=2)

    # 6 diretos + 2 vagas do Play-In = 8 classificados por simulação, nesta conferência de 10 times.
    assert (result["made_playoffs"].sum(axis=1) == 8).all()
    # Ninguém pode estar fora do Play-In e mesmo assim classificado sem ter sido direto.
    eliminated_but_qualified = (~result["play_in_slot"]) & (~result["direct_playoffs"]) & result["made_playoffs"]
    assert not eliminated_but_qualified.any()


def test_simulate_season_probabilities_are_consistent(season_games, bundle):
    summary = simulate_season(
        season_games, bundle, "TEST-SEASON", "2024-02-01", n_simulations=500, seed=3
    )

    assert set(summary["team"]) == set(TEAMS)
    assert (summary["prob_playoffs"] >= 0).all() and (summary["prob_playoffs"] <= 1).all()
    assert (summary["prob_direct_playoffs"] <= summary["prob_playoffs"] + 1e-9).all()

    strongest = summary.set_index("team").loc[TEAMS[0], "prob_playoffs"]
    weakest = summary.set_index("team").loc[TEAMS[9], "prob_playoffs"]
    assert strongest > weakest
