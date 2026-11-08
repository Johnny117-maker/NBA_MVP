import numpy as np
import pandas as pd
import pytest

from src.data import generate_demo_games, team_snapshot
from src.features import engineer_features
from src.team_strength import (
    ELO_BASE,
    ELO_SEASON_CARRY,
    current_elo_ratings,
    elo_history,
    ensure_elo_columns,
    season_key,
)


def _games(rows):
    frame = pd.DataFrame(rows, columns=["game_date", "home_team", "away_team", "home_points", "away_points"])
    frame["game_date"] = pd.to_datetime(frame["game_date"])
    return frame


def test_first_game_starts_both_teams_at_the_base_rating():
    games = _games([("2025-11-01", "A", "B", 110, 100)])
    home_pre, away_pre, ratings, _ = elo_history(games)
    assert home_pre[0] == away_pre[0] == ELO_BASE
    assert ratings["A"] > ELO_BASE > ratings["B"]
    assert ratings["A"] - ELO_BASE == pytest.approx(ELO_BASE - ratings["B"])


def test_pregame_elo_ignores_the_game_itself_and_the_future():
    rows = [
        ("2025-11-01", "A", "B", 110, 100),
        ("2025-11-03", "B", "C", 90, 120),
        ("2025-11-05", "A", "C", 100, 99),
    ]
    before, _, _, _ = elo_history(_games(rows))
    changed = rows[:2] + [("2025-11-05", "A", "C", 0, 200), ("2026-01-01", "A", "B", 200, 0)]
    after, _, _, _ = elo_history(_games(changed))
    # O Elo de cada jogo existente não muda quando o placar do próprio jogo ou jogos futuros mudam.
    np.testing.assert_allclose(before[:3], after[:3])


def test_blowouts_move_ratings_more_than_close_wins():
    close = current_elo_ratings(_games([("2025-11-01", "A", "B", 101, 100)]))
    blowout = current_elo_ratings(_games([("2025-11-01", "A", "B", 130, 100)]))
    assert blowout["A"] > close["A"]


def test_upset_wins_move_ratings_more_than_expected_wins():
    base = [("2025-11-01", "A", "B", 130, 100), ("2025-11-03", "A", "B", 130, 100)]
    favorite_wins = current_elo_ratings(_games([*base, ("2025-11-05", "A", "B", 110, 100)]))
    underdog_wins = current_elo_ratings(_games([*base, ("2025-11-05", "A", "B", 100, 110)]))
    gain = favorite_wins["A"] - current_elo_ratings(_games(base))["A"]
    loss = current_elo_ratings(_games(base))["A"] - underdog_wins["A"]
    assert loss > gain


def test_ratings_regress_toward_the_mean_between_seasons():
    games = _games([("2025-11-01", "A", "B", 130, 100), ("2026-11-01", "A", "B", 100, 100)])
    home_pre, _, ratings, _ = elo_history(games)
    first = current_elo_ratings(games.head(1))["A"]
    assert home_pre[1] == pytest.approx(ELO_BASE + ELO_SEASON_CARRY * (first - ELO_BASE))
    assert ratings["A"] == pytest.approx(home_pre[1])  # empate não altera o Elo


def test_as_of_in_a_new_season_applies_the_same_regression():
    games = _games([("2026-04-01", "A", "B", 130, 100)])
    same_season = current_elo_ratings(games, as_of=pd.Timestamp("2026-04-10").date())
    next_season = current_elo_ratings(games, as_of=pd.Timestamp("2026-10-25").date())
    assert next_season["A"] == pytest.approx(ELO_BASE + ELO_SEASON_CARRY * (same_season["A"] - ELO_BASE))


def test_season_key_starts_a_new_season_in_august():
    keys = season_key(["2026-07-31", "2026-08-01", "2027-04-10"])
    assert keys.tolist() == [2025, 2026, 2026]


def _round_robin_games(days=40, seed=5):
    """Calendário realista: cada time joga no máximo uma vez por dia."""
    rng = np.random.default_rng(seed)
    teams = ["T0", "T1", "T2", "T3", "T4", "T5"]
    rows = []
    for day in range(days):
        order = rng.permutation(teams)
        for left, right in zip(order[::2], order[1::2], strict=True):
            rows.append((pd.Timestamp("2025-11-01") + pd.Timedelta(day, unit="D"), left, right,
                         int(rng.integers(90, 130)), int(rng.integers(90, 130))))
    return _games(rows)


def test_input_order_does_not_change_the_result():
    games = _round_robin_games()
    shuffled = games.sample(frac=1.0, random_state=3)
    home_a, away_a, ratings_a, _ = elo_history(games)
    home_b, away_b, ratings_b, _ = elo_history(shuffled)
    for before, after in ((home_a, home_b), (away_a, away_b)):
        expected = pd.Series(before, index=games.index).loc[shuffled.index].to_numpy()
        np.testing.assert_allclose(after, expected)
    assert ratings_a == pytest.approx(ratings_b)


def test_missing_columns_raise_a_clear_error():
    with pytest.raises(ValueError, match="home_points"):
        elo_history(pd.DataFrame({"game_date": [], "home_team": [], "away_team": [], "away_points": []}))


def test_engineered_games_carry_pregame_elo_and_snapshot_uses_the_latest_rating():
    games = engineer_features(
        _games(
            [("2025-11-01", "Celtics", "Knicks", 120, 100), ("2025-11-03", "Knicks", "Celtics", 99, 110)]
        ).assign(game_id=["1", "2"], season="2025-26")
    )
    assert {"home_elo", "away_elo"}.issubset(games.columns)
    assert games.loc[0, ["home_elo", "away_elo"]].tolist() == [ELO_BASE, ELO_BASE]
    assert games.loc[1, "away_elo"] > games.loc[1, "home_elo"]
    assert team_snapshot(games, "Celtics")["elo"] > team_snapshot(games, "Knicks")["elo"]
    assert "elo" not in team_snapshot(games, "Celtics", with_elo=False)


def test_ensure_elo_columns_does_not_recompute_prepared_games():
    games = generate_demo_games(60)
    enriched = ensure_elo_columns(games)
    assert {"home_elo", "away_elo"}.issubset(enriched.columns)
    assert ensure_elo_columns(enriched) is enriched
