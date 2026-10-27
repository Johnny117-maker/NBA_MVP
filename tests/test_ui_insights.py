import sqlite3

import pandas as pd
import pytest

from src.store import read_dashboard_leaders
from src.ui.insights import latest_season_games, performance_bars, scoring_frequencies, team_form_table


def test_scoring_map_includes_ties_only_in_until_and_handles_missing():
    history = pd.DataFrame({"points_for": [90, 100, 110, None]})
    rates = scoring_frequencies(history, [100, 110])
    assert rates.loc["Acima", 100] == pytest.approx(1 / 3)
    assert rates.loc["Até", 100] == pytest.approx(2 / 3)
    assert rates.loc["Acima", 110] == 0
    assert rates.loc["Até", 110] == 1
    assert scoring_frequencies(history.iloc[:0], [100]).isna().all().all()


def test_team_cards_use_recent_window_and_lower_defense_ranks_first():
    games = pd.DataFrame(
        {
            "game_date": pd.date_range("2026-01-01", periods=3),
            "home_team": ["Boston Celtics"] * 3,
            "away_team": ["New York Knicks"] * 3,
            "home_points": [150, 100, 110],
            "away_points": [80, 120, 100],
            "home_off_rating": [150, 100, 110],
            "away_off_rating": [80, 120, 100],
            "home_def_rating": [80, 120, 100],
            "away_def_rating": [150, 100, 110],
            "home_net_rating": [70, -20, 10],
            "away_net_rating": [-70, 20, -10],
            "home_last10_win_pct": [0.5] * 3,
            "away_last10_win_pct": [0.5] * 3,
        }
    )
    table = team_form_table(games, window=2).set_index("team")
    boston = table.loc["Boston Celtics"]
    assert boston["points_for"] == 105
    assert boston["wins"] == 2  # campanha completa, sem limitar à janela recente
    assert boston["form"] == [0, 1]
    assert boston["rank_def_rating"] == 2
    assert table.loc["New York Knicks", "rank_def_rating"] == 1


def test_latest_season_is_determined_by_game_date_not_row_order():
    frame = pd.DataFrame(
        {"game_date": pd.to_datetime(["2026-01-01", "2024-01-01"]), "season": ["2025-26", "2023-24"]}
    )
    assert latest_season_games(frame)["season"].tolist() == ["2025-26"]


def test_dashboard_leaders_exclude_old_seasons_and_small_samples_and_follow_trades(tmp_path):
    db_path = tmp_path / "leaders.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE player_game_stats (player_id, player_name, team, game_date, "
            "game_id, season, pts, reb, ast)"
        )
        rows = [
            (1, "Atleta A", "BOS" if i < 9 else "LAL", f"2026-01-{i + 1:02d}", str(i), "2025-26", 10, 5, 3)
            for i in range(10)
        ]
        rows += [(2, "Amostra curta", "NYK", "2026-01-10", "x", "2025-26", 99, 1, 1)]
        rows += [(1, "Atleta A", "BOS", "2024-01-10", "old", "2023-24", 100, 1, 1)]
        connection.executemany("INSERT INTO player_game_stats VALUES (?,?,?,?,?,?,?,?,?)", rows)
    leaders = read_dashboard_leaders(db_path)
    assert leaders["player_id"].tolist() == [1]
    assert leaders.iloc[0]["team"] == "LAL"
    assert leaders.iloc[0]["pts"] == 10
    assert leaders.iloc[0]["games"] == 10


def test_performance_bars_have_chronological_order_and_unambiguous_tie_color():
    frame = pd.DataFrame(
        {
            "game_date": pd.to_datetime(["2026-01-02", "2026-01-01"]),
            "opponent": ["BOS", "NYK"],
            "pts": [20, 10],
        }
    )
    chart = performance_bars(frame, "pts", "Pontos", 10)
    assert list(chart.data[0].y) == [10, 20]
    assert list(chart.data[0].marker.color) == ["#ef4444", "#22c55e"]
