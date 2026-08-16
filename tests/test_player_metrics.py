from datetime import timedelta

import pandas as pd
import pytest

from src.player_metrics import (
    add_efficiency_metrics,
    add_per36_rates,
    compare_players,
    estimate_team_game_totals,
    list_players,
    player_season_summary,
    player_snapshot,
)


def _raw_player_games() -> pd.DataFrame:
    base = {
        "game_id": "G1",
        "game_date": pd.Timestamp("2024-01-10"),
        "season": "2023-24",
    }
    return pd.DataFrame(
        [
            {
                **base,
                "player_id": 1,
                "player_name": "A One",
                "team": "A",
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
            },
            {
                **base,
                "player_id": 2,
                "player_name": "A Two",
                "team": "A",
                "opponent": "B",
                "is_home": True,
                "minutes": 20,
                "pts": 8,
                "oreb": 1,
                "dreb": 2,
                "reb": 3,
                "ast": 2,
                "stl": 0,
                "blk": 1,
                "tov": 1,
                "pf": 1,
                "fgm": 3,
                "fga": 8,
                "fg3m": 1,
                "fg3a": 3,
                "ftm": 1,
                "fta": 2,
            },
            {
                **base,
                "player_id": 3,
                "player_name": "B One",
                "team": "B",
                "opponent": "A",
                "is_home": False,
                "minutes": 25,
                "pts": 15,
                "oreb": 2,
                "dreb": 3,
                "reb": 5,
                "ast": 3,
                "stl": 1,
                "blk": 0,
                "tov": 2,
                "pf": 3,
                "fgm": 6,
                "fga": 12,
                "fg3m": 1,
                "fg3a": 4,
                "ftm": 2,
                "fta": 3,
            },
        ]
    )


def test_estimate_team_game_totals_sums_only_within_team():
    totals = estimate_team_game_totals(_raw_player_games())
    team_a = totals[(totals["game_id"] == "G1") & (totals["team"] == "A")].iloc[0]

    assert team_a["team_minutes"] == 50
    assert team_a["team_fga"] == 23
    assert team_a["team_fta"] == 7
    assert team_a["team_tov"] == 3


def test_efficiency_metrics_match_manual_formulas():
    games = add_efficiency_metrics(_raw_player_games())
    player_a1 = games[games["player_id"] == 1].iloc[0]

    expected_ts = 22 / (2 * (15 + 0.44 * 5))
    expected_efg = (8 + 0.5 * 2) / 15
    expected_ast_to = 5 / 2
    expected_usage = 100 * ((15 + 0.44 * 5 + 2) * (50 / 5)) / (30 * (23 + 0.44 * 7 + 3))

    assert player_a1["true_shooting_pct"] == pytest.approx(expected_ts)
    assert player_a1["effective_fg_pct"] == pytest.approx(expected_efg)
    assert player_a1["ast_to_ratio"] == pytest.approx(expected_ast_to)
    assert player_a1["usage_pct"] == pytest.approx(expected_usage)


def test_per36_rates_scale_by_minutes():
    games = add_per36_rates(_raw_player_games())
    player_a1 = games[games["player_id"] == 1].iloc[0]

    assert player_a1["pts_per36"] == pytest.approx(22 * 36 / 30)


def test_list_players_and_summary_and_compare():
    raw = _raw_player_games()
    games = add_per36_rates(add_efficiency_metrics(raw))

    players = list_players(games)
    assert set(players["player_id"]) == {1, 2, 3}

    summary = player_season_summary(games)
    assert set(summary["player_id"]) == {1, 2, 3}
    assert summary.loc[summary["player_id"] == 1, "pts_mean"].iloc[0] == 22

    comparison = compare_players(games, [1, 3])
    assert list(comparison.columns) == ["A One", "B One"]


def test_player_snapshot_isolates_current_stint():
    rows = []
    game_number = 0
    for team, minutes, pts, count in (("Team A", 20, 12, 8), ("Team B", 34, 26, 5)):
        for _ in range(count):
            rows.append(
                {
                    "player_id": 1,
                    "player_name": "A One",
                    "team": team,
                    "game_id": f"G{game_number}",
                    "game_date": pd.Timestamp("2024-01-01") + timedelta(days=game_number * 2),
                    "minutes": minutes,
                    "pts": pts,
                    "reb": 5,
                    "ast": 3,
                    "fga": 10,
                    "fta": 3,
                    "true_shooting_pct": 0.55,
                    "usage_pct": 24.0,
                }
            )
            game_number += 1
    games = pd.DataFrame(rows)

    snapshot = player_snapshot(games, player_id=1)

    assert snapshot["games_since_trade"] == 5
    # Passagem atual (Time B) tem minutos bem diferentes da carreira, que
    # ainda arrasta os 8 jogos do Time A.
    assert snapshot["minutes_avg10_stint"] == pytest.approx(34.0)
    assert snapshot["minutes_avg10"] != pytest.approx(snapshot["minutes_avg10_stint"])
