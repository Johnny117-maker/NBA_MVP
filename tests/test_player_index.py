from datetime import timedelta

import pandas as pd
import pytest

from src.player_index import build_player_index, qualified_players
from src.player_metrics import add_advanced_rate_metrics, add_efficiency_metrics, add_per36_rates

# (team, minutes, fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf)
PLAYER_PROFILES = {
    1: ("Alpha", 34, 8, 15, 2, 5, 4, 5, 1, 4, 9, 1, 0, 3, 2),  # Creator: uso e assistências altos
    2: ("Alpha", 30, 5, 9, 0, 0, 2, 3, 4, 9, 1, 0, 3, 1, 3),  # Rim protector: bloqueios e rebotes altos
    3: ("Alpha", 7, 3, 5, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0, 1),  # Poucos minutos: não deve qualificar
    4: ("Beta", 28, 4, 10, 1, 3, 2, 2, 1, 3, 2, 1, 0, 2, 2),
    5: ("Beta", 26, 3, 8, 0, 2, 1, 1, 1, 2, 1, 0, 0, 1, 2),
    6: ("Beta", 24, 3, 7, 0, 1, 1, 2, 1, 2, 1, 0, 0, 1, 2),
}


def _fabricated_league(n_games: int = 20) -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2024-01-01")
    for game_number in range(n_games):
        game_id = f"G{game_number}"
        game_date = start + timedelta(days=game_number * 2)
        alpha_is_home = game_number % 2 == 0
        for player_id, profile in PLAYER_PROFILES.items():
            team, minutes, fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf = profile
            is_home = alpha_is_home if team == "Alpha" else not alpha_is_home
            opponent = "Beta" if team == "Alpha" else "Alpha"
            pts = 2 * (fgm - fg3m) + 3 * fg3m + ftm
            rows.append(
                {
                    "game_id": game_id,
                    "game_date": game_date,
                    "season": "TEST",
                    "player_id": player_id,
                    "player_name": f"Player {player_id}",
                    "team": team,
                    "opponent": opponent,
                    "is_home": is_home,
                    "minutes": minutes,
                    "pts": pts,
                    "oreb": oreb,
                    "dreb": dreb,
                    "reb": oreb + dreb,
                    "ast": ast,
                    "stl": stl,
                    "blk": blk,
                    "tov": tov,
                    "pf": pf,
                    "fgm": fgm,
                    "fga": fga,
                    "fg3m": fg3m,
                    "fg3a": fg3a,
                    "ftm": ftm,
                    "fta": fta,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def indexed_players() -> pd.DataFrame:
    raw = _fabricated_league()
    with_efficiency = add_efficiency_metrics(raw)
    with_rates = add_per36_rates(with_efficiency)
    return add_advanced_rate_metrics(with_rates)


def test_qualified_players_excludes_low_minutes_bench(indexed_players):
    qualified = qualified_players(indexed_players)
    qualified_ids = qualified["player_id"].tolist()

    assert 3 not in qualified_ids  # média de 7 min, abaixo do mínimo (10)
    assert 1 in qualified_ids
    assert 2 in qualified_ids


def test_percentiles_and_naps_are_bounded(indexed_players):
    index = build_player_index(indexed_players)

    dimension_columns = [
        "efficiency_pct",
        "creation_pct",
        "defense_pct",
        "rebounding_pct",
        "consistency_pct",
        "availability_pct",
    ]
    for column in dimension_columns:
        assert index[column].dropna().between(0, 100).all()
    assert index["naps"].dropna().between(0, 100).all()


def test_classify_style_identifies_creator_and_rim_protector(indexed_players):
    index = build_player_index(indexed_players)

    creator_style = index.loc[index["player_id"] == 1, "style"].iloc[0]
    rim_protector_style = index.loc[index["player_id"] == 2, "style"].iloc[0]

    assert creator_style == "Criador principal"
    assert rim_protector_style == "Protetor de aro"
