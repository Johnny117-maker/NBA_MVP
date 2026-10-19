from datetime import timedelta

import pandas as pd
import pytest

from src.player_features import (
    EMA_HALFLIFE_FAST,
    EMA_HALFLIFE_SLOW,
    add_opponent_context,
    add_rolling_features,
    assign_team_stints,
    effective_starter_flag,
)


def _fabricated_player_games() -> pd.DataFrame:
    dates = ["2024-01-01", "2024-01-03", "2024-01-06", "2024-01-08", "2024-01-15"]
    minutes = [30, 32, 28, 20, 10]
    pts = [20, 22, 18, 10, 4]
    reb = [8, 7, 6, 4, 2]
    ast = [5, 6, 4, 3, 1]
    fga = [15, 16, 13, 8, 3]
    fta = [4, 4, 3, 2, 1]
    ts_pct = [0.55, 0.56, 0.54, 0.50, 0.48]
    usg_pct = [28.0, 29.0, 27.0, 22.0, 18.0]

    rows = []
    for i, date in enumerate(dates):
        rows.append(
            {
                "player_id": 1,
                "player_name": "A One",
                "team": "Team A",
                "game_id": f"G{i}",
                "game_date": pd.Timestamp(date),
                "minutes": minutes[i],
                "pts": pts[i],
                "reb": reb[i],
                "ast": ast[i],
                "fga": fga[i],
                "fta": fta[i],
                "true_shooting_pct": ts_pct[i],
                "usage_pct": usg_pct[i],
            }
        )
    return pd.DataFrame(rows)


def _traded_player_games() -> pd.DataFrame:
    """Um jogador com 8 jogos no Time A e depois 5 jogos no Time B."""
    rows = []
    game_number = 0
    for team, minutes, pts, fga, fta, ts_pct, usg_pct, count in (
        ("Team A", 20, 12, 10, 3, 0.50, 20.0, 8),
        ("Team B", 34, 26, 18, 6, 0.60, 30.0, 5),
    ):
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
                    "fga": fga,
                    "fta": fta,
                    "true_shooting_pct": ts_pct,
                    "usage_pct": usg_pct,
                }
            )
            game_number += 1
    return pd.DataFrame(rows)


def _fabricated_team_games() -> pd.DataFrame:
    """Cinco jogos antigos de cada time, antes de qualquer jogo do jogador."""
    rows = []
    for i in range(5):
        game_date = pd.Timestamp("2023-12-01") + timedelta(days=i)
        rows.append(
            {
                "game_date": game_date,
                "home_team": "Defesa Fraca",
                "away_team": "Rival A",
                "home_points": 100,
                "away_points": 130,  # Defesa Fraca sofreu 130 nesse jogo
            }
        )
        rows.append(
            {
                "game_date": game_date,
                "home_team": "Defesa Forte",
                "away_team": "Rival B",
                "home_points": 100,
                "away_points": 90,  # Defesa Forte sofreu 90 nesse jogo
            }
        )
    return pd.DataFrame(rows)


def _player_games_against_two_defenses() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": 1,
                "player_name": "A One",
                "team": "Meu Time",
                "opponent": "Defesa Fraca",
                "game_date": pd.Timestamp("2024-01-10"),
                "minutes": 30,
                "pts": 20,
                "reb": 5,
                "ast": 4,
                "fga": 15,
                "fta": 4,
                "true_shooting_pct": 0.55,
                "usage_pct": 25.0,
            },
            {
                "player_id": 1,
                "player_name": "A One",
                "team": "Meu Time",
                "opponent": "Defesa Forte",
                "game_date": pd.Timestamp("2024-01-12"),
                "minutes": 30,
                "pts": 20,
                "reb": 5,
                "ast": 4,
                "fga": 15,
                "fta": 4,
                "true_shooting_pct": 0.55,
                "usage_pct": 25.0,
            },
        ]
    )


def test_add_opponent_context_uses_real_defensive_history():
    result = add_opponent_context(_player_games_against_two_defenses(), _fabricated_team_games())

    weak_defense = result[result["opponent"] == "Defesa Fraca"].iloc[0]
    strong_defense = result[result["opponent"] == "Defesa Forte"].iloc[0]

    assert weak_defense["opponent_def_rating"] == pytest.approx(130.0)
    assert strong_defense["opponent_def_rating"] == pytest.approx(90.0)



def test_opponent_fallback_is_not_changed_by_future_defensive_games():
    players = pd.DataFrame(
        [{
            "player_id": 1, "player_name": "A One", "team": "Meu Time",
            "opponent": "Defesa", "game_date": pd.Timestamp("2024-01-02"),
            "minutes": 30, "pts": 20, "reb": 5, "ast": 4, "fga": 15,
            "fta": 4, "true_shooting_pct": 0.55, "usage_pct": 25.0,
        }]
    )
    historical = pd.DataFrame([
        {"game_date": pd.Timestamp("2024-01-01"), "home_team": "Defesa",
         "away_team": "Rival A", "home_points": 100, "away_points": 100},
    ])
    with_future = pd.concat([
        historical,
        pd.DataFrame([
            {"game_date": pd.Timestamp("2024-01-04"), "home_team": "Defesa",
             "away_team": "Rival B", "home_points": 100, "away_points": 190},
        ]),
    ], ignore_index=True)
    without_future = add_opponent_context(players, historical).iloc[0]["opponent_def_rating"]
    with_future_value = add_opponent_context(players, with_future).iloc[0]["opponent_def_rating"]
    assert without_future == pytest.approx(100.0)
    assert with_future_value == pytest.approx(without_future)

def test_first_game_uses_default_values_not_future_data():
    games = add_rolling_features(_fabricated_player_games())
    first_game = games.iloc[0]

    # A primeira data não pode usar a média de toda a base: o fallback é um
    # prior fixo até que exista histórico anterior conhecido.
    assert first_game["minutes_avg5"] == pytest.approx(18.0)
    assert first_game["minutes_avg10"] == pytest.approx(18.0)
    assert first_game["rest_days"] == 3  # default, sem jogo anterior



def test_missing_player_fallback_uses_only_dates_before_the_prediction():
    rows = pd.DataFrame(
        [
            {"player_id": 1, "player_name": "First", "team": "A", "game_id": "G1",
             "game_date": pd.Timestamp("2024-01-01"), "minutes": 20, "pts": 10, "reb": 3,
             "ast": 2, "fga": 8, "fta": 2, "true_shooting_pct": 0.5, "usage_pct": 20.0},
            {"player_id": 2, "player_name": "Second", "team": "B", "game_id": "G2",
             "game_date": pd.Timestamp("2024-01-02"), "minutes": 30, "pts": 15, "reb": 4,
             "ast": 3, "fga": 10, "fta": 3, "true_shooting_pct": 0.55, "usage_pct": 22.0},
            {"player_id": 3, "player_name": "Future", "team": "C", "game_id": "G3",
             "game_date": pd.Timestamp("2024-01-03"), "minutes": 48, "pts": 60, "reb": 15,
             "ast": 12, "fga": 40, "fta": 20, "true_shooting_pct": 0.9, "usage_pct": 45.0},
        ]
    )
    result = add_rolling_features(rows)
    second = result[result["player_id"] == 2].iloc[0]
    # O jogador 2 não tem histórico próprio: deve herdar os 20 minutos do
    # único dia anterior, independentemente dos valores extremos em 03/01.
    assert second["minutes_avg5"] == pytest.approx(20.0)
    assert second["fga_per_min_avg3"] == pytest.approx(8 / 20)
    assert second["ts_pct_avg3"] == pytest.approx(0.5)


def test_recent_features_use_only_prior_games():
    rows = _fabricated_player_games()
    result = add_rolling_features(rows)
    fourth = result.iloc[3]
    assert fourth["pts_avg3"] == pytest.approx((20 + 22 + 18) / 3)
    expected_rate = (15 / 30 + 16 / 32 + 13 / 28) / 3
    assert fourth["fga_per_min_avg3"] == pytest.approx(expected_rate)

def test_rest_days_matches_real_gap_between_games():
    games = add_rolling_features(_fabricated_player_games())
    second_game = games.iloc[1]
    assert second_game["rest_days"] == 2  # 2024-01-03 - 2024-01-01


def test_rolling_average_uses_only_prior_games():
    games = add_rolling_features(_fabricated_player_games())
    third_game = games.iloc[2]

    # Média móvel exponencial dos dois primeiros jogos (30, 32) — não a média
    # flat — mesma fórmula usada em `_per_player_rolling`.
    expected_minutes = pd.Series([30, 32]).ewm(halflife=EMA_HALFLIFE_FAST, min_periods=1).mean().iloc[-1]
    assert third_game["minutes_avg5"] == pytest.approx(expected_minutes)

    expected_pts_rate = (
        pd.Series([20 / 30, 22 / 32]).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean().iloc[-1]
    )
    assert third_game["pts_per_min_avg10"] == pytest.approx(expected_pts_rate)


def test_ema_reacts_faster_than_a_flat_average_would():
    """Depois de um salto de minutos, a EMA já reage antes da média flat reagiria."""
    minutes = [10, 10, 10, 10, 30, 30]
    rows = []
    for i, value in enumerate(minutes):
        rows.append(
            {
                "player_id": 1,
                "player_name": "A One",
                "team": "Team A",
                "game_id": f"G{i}",
                "game_date": pd.Timestamp("2024-01-01") + timedelta(days=i * 2),
                "minutes": value,
                "pts": value,
                "reb": 2,
                "ast": 1,
                "fga": 8,
                "fta": 2,
                "true_shooting_pct": 0.5,
                "usage_pct": 20.0,
            }
        )
    games = add_rolling_features(pd.DataFrame(rows))

    last_game = games.iloc[-1]
    flat_average_of_prior_five = sum(minutes[:5]) / 5  # (10+10+10+10+30)/5 = 14
    assert last_game["minutes_avg5"] > flat_average_of_prior_five


def test_effective_starter_flag_falls_back_to_minutes_above_team_median_when_missing():
    games = pd.DataFrame(
        [
            {"game_id": "G1", "team": "A", "minutes": 30},
            {"game_id": "G1", "team": "A", "minutes": 10},
        ]
    )
    flags = effective_starter_flag(games)
    assert list(flags) == [True, False]


def test_effective_starter_flag_prefers_real_data_over_the_approximation():
    games = pd.DataFrame(
        [
            # Dado real diz banco, mesmo jogando mais minutos que a mediana.
            {"game_id": "G1", "team": "A", "minutes": 30, "is_starter": False},
            # Dado real diz titular, mesmo jogando menos minutos que a mediana.
            {"game_id": "G1", "team": "A", "minutes": 10, "is_starter": True},
            # Sem dado real (ainda não coletado) -> cai na aproximação por mediana (20).
            {"game_id": "G1", "team": "A", "minutes": 20, "is_starter": pd.NA},
        ]
    )
    flags = effective_starter_flag(games)
    assert list(flags) == [False, True, False]


def test_add_rolling_features_produces_a_starter_rate_between_zero_and_one():
    games = add_rolling_features(_fabricated_player_games())
    assert games["starter_rate_avg10"].between(0, 1).all()
    assert games["starter_rate_avg10_stint"].between(0, 1).all()
    assert games["starter_rate_avg10"].notna().all()


def test_assign_team_stints_detects_trade():
    games = assign_team_stints(_traded_player_games())

    team_a_games = games[games["team"] == "Team A"]
    team_b_games = games[games["team"] == "Team B"]

    assert team_a_games["team_stint_id"].nunique() == 1
    assert team_b_games["team_stint_id"].nunique() == 1
    assert team_a_games["team_stint_id"].iloc[0] != team_b_games["team_stint_id"].iloc[0]

    assert list(team_a_games["games_since_trade"]) == list(range(8))
    assert list(team_b_games["games_since_trade"]) == list(range(5))


def test_stint_rolling_average_does_not_leak_across_trade():
    games = add_rolling_features(_traded_player_games())
    team_b_games = games[games["team"] == "Team B"].reset_index(drop=True)

    # Primeiro jogo do Time B: sem histórico na passagem, cai na média de carreira
    # (que inclui os jogos do Time A) — o passado ainda influencia, como o
    # planejamento pede.
    first_game_b = team_b_games.iloc[0]
    assert first_game_b["minutes_avg10_stint"] == pytest.approx(first_game_b["minutes_avg10"])
    assert first_game_b["games_since_trade"] == 0

    # A partir do segundo jogo do Time B, a média "_stint" só usa jogos do Time B
    # (minutos=34), bem diferente da média de carreira (que ainda arrasta o Time A,
    # minutos=20).
    second_game_b = team_b_games.iloc[1]
    assert second_game_b["minutes_avg10_stint"] == pytest.approx(34.0)
    assert second_game_b["minutes_avg10_stint"] != pytest.approx(second_game_b["minutes_avg10"])
    assert second_game_b["games_since_trade"] == 1
