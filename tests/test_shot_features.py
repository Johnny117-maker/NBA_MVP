import numpy as np
import pandas as pd

from src.shot_features import (
    add_shot_value,
    compare_periods,
    compare_to_league,
    compare_to_opponent_defense,
    filter_shots,
    league_zone_rates,
    opponent_zone_defense,
    shot_indicators,
    zone_summary,
)


def _shot(
    game_id="G1",
    game_date="2024-01-01",
    season="2024-25",
    team_name="Boston Celtics",
    opponent="New York Knicks",
    period=1,
    shot_zone_basic="Restricted Area",
    shot_type="2PT Field Goal",
    shot_distance=2,
    shot_made=True,
    game_event_id=1,
) -> dict:
    return {
        "player_id": 201,
        "player_name": "Jayson Tatum",
        "game_id": game_id,
        "game_event_id": game_event_id,
        "season": season,
        "game_date": pd.Timestamp(game_date),
        "team_id": 1,
        "team_name": team_name,
        "opponent": opponent,
        "period": period,
        "minutes_remaining": 5,
        "seconds_remaining": 0,
        "event_type": "Made Shot" if shot_made else "Missed Shot",
        "action_type": "Layup Shot",
        "shot_type": shot_type,
        "shot_zone_basic": shot_zone_basic,
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "Less Than 8 ft.",
        "shot_distance": shot_distance,
        "loc_x": 0,
        "loc_y": 0,
        "loc_x_ft": 0.0,
        "loc_y_ft": 0.0,
        "shot_attempted": 1,
        "shot_made": shot_made,
        "source": "nba_api",
    }


def _sample_shots() -> pd.DataFrame:
    rows = [
        # 4 arremessos no aro, 3 convertidos
        _shot(shot_zone_basic="Restricted Area", shot_type="2PT Field Goal", shot_distance=1, shot_made=True, game_event_id=1),
        _shot(shot_zone_basic="Restricted Area", shot_type="2PT Field Goal", shot_distance=2, shot_made=True, game_event_id=2),
        _shot(shot_zone_basic="Restricted Area", shot_type="2PT Field Goal", shot_distance=1, shot_made=True, game_event_id=3),
        _shot(shot_zone_basic="Restricted Area", shot_type="2PT Field Goal", shot_distance=2, shot_made=False, game_event_id=4),
        # 2 arremessos de três frontal, 1 convertido
        _shot(shot_zone_basic="Above the Break 3", shot_type="3PT Field Goal", shot_distance=26, shot_made=True, game_event_id=5),
        _shot(shot_zone_basic="Above the Break 3", shot_type="3PT Field Goal", shot_distance=27, shot_made=False, game_event_id=6),
        # 1 arremesso de meia distância, errado
        _shot(shot_zone_basic="Mid-Range", shot_type="2PT Field Goal", shot_distance=15, shot_made=False, game_event_id=7),
    ]
    return pd.DataFrame(rows)


def test_add_shot_value_detects_two_and_three_pointers():
    data = add_shot_value(_sample_shots())
    assert set(data.loc[data["shot_zone_basic"] == "Above the Break 3", "shot_value"]) == {3}
    assert set(data.loc[data["shot_zone_basic"] == "Restricted Area", "shot_value"]) == {2}


def test_zone_summary_computes_volume_efficiency_and_points_per_shot():
    summary = zone_summary(_sample_shots()).set_index("shot_zone_basic")

    rim = summary.loc["Restricted Area"]
    assert rim["attempts"] == 4
    assert rim["makes"] == 3
    assert rim["fg_pct"] == 0.75
    assert rim["frequency"] == 4 / 7
    assert rim["points"] == 6  # 3 conversões de 2 pontos
    assert rim["points_per_shot"] == 1.5
    assert rim["zone_label"] == "Aro"

    three = summary.loc["Above the Break 3"]
    assert three["attempts"] == 2
    assert three["makes"] == 1
    assert three["points"] == 3
    assert three["points_per_shot"] == 1.5


def test_zone_summary_sorted_by_attempts_descending():
    summary = zone_summary(_sample_shots())
    assert list(summary["attempts"]) == sorted(summary["attempts"], reverse=True)
    assert summary.iloc[0]["shot_zone_basic"] == "Restricted Area"


def test_zone_summary_empty_input_returns_empty_frame_with_columns():
    summary = zone_summary(pd.DataFrame())
    assert summary.empty
    assert "shot_zone_basic" in summary.columns
    assert "points_per_shot" in summary.columns


def test_compare_to_league_shrinks_small_sample_toward_league_average():
    # "Liga": 1000 tentativas no aro com 50% de aproveitamento.
    league_rows = [
        _shot(shot_zone_basic="Restricted Area", shot_made=(i % 2 == 0), game_event_id=1000 + i)
        for i in range(1000)
    ]
    league = pd.DataFrame(league_rows)
    league_rates = league_zone_rates(league)

    # Jogador: só 4 tentativas no aro, 100% de aproveitamento (amostra minúscula).
    player_rows = [
        _shot(shot_zone_basic="Restricted Area", shot_made=True, game_event_id=2000 + i)
        for i in range(4)
    ]
    player_summary = zone_summary(pd.DataFrame(player_rows))

    compared = compare_to_league(player_summary, league_rates).set_index("shot_zone_basic")
    rim = compared.loc["Restricted Area"]

    assert rim["fg_pct"] == 1.0
    assert abs(rim["league_fg_pct"] - 0.5) < 0.01
    # A suavização deve ficar entre o valor bruto (100%) e a média da liga (50%),
    # bem mais perto da liga porque a amostra do jogador é pequena.
    assert 0.5 < rim["shrunk_fg_pct"] < 0.75


def test_shot_indicators_basic_totals_and_percentages():
    indicators = shot_indicators(_sample_shots())

    assert indicators["total_attempts"] == 7
    assert indicators["total_makes"] == 4
    assert indicators["fg_pct"] == 4 / 7
    # eFG% = (FGM + 0.5*3PM) / FGA = (4 + 0.5*1) / 7
    assert abs(indicators["efg_pct"] - (4.5 / 7)) < 1e-9
    assert indicators["most_used_zone"] == "Aro"
    assert indicators["pct_rim"] == 4 / 7
    assert indicators["pct_three"] == 2 / 7
    assert indicators["pct_midrange"] == 1 / 7


def test_shot_indicators_empty_input_returns_empty_dict():
    assert shot_indicators(pd.DataFrame()) == {}


def test_shot_indicators_with_league_rates_flags_best_and_worst_zones():
    # Liga: aro com FG% baixo (30%), então o jogador (75% no aro) fica bem acima.
    league_rows = [
        _shot(shot_zone_basic="Restricted Area", shot_made=(i < 3), game_event_id=3000 + i)
        for i in range(10)
    ] + [
        _shot(shot_zone_basic="Above the Break 3", shot_made=(i < 5), game_event_id=4000 + i)
        for i in range(10)
    ]
    league_rates = league_zone_rates(pd.DataFrame(league_rows))

    shots = _sample_shots()
    # Reforça a amostra do aro para passar do mínimo de tentativas (5).
    extra_rim = [
        _shot(shot_zone_basic="Restricted Area", shot_made=True, game_event_id=5000 + i)
        for i in range(3)
    ]
    shots = pd.concat([shots, pd.DataFrame(extra_rim)], ignore_index=True)

    indicators = shot_indicators(shots, league_rates=league_rates)
    assert indicators["best_diff_zone"] == "Aro"
    assert indicators["best_diff_points_per_shot"] > 0


def test_filter_shots_by_season_opponent_and_date_range():
    shots = pd.DataFrame(
        [
            _shot(game_date="2023-11-01", season="2023-24", opponent="Miami Heat", game_event_id=1),
            _shot(game_date="2024-01-01", season="2024-25", opponent="New York Knicks", game_event_id=2),
            _shot(game_date="2024-02-01", season="2024-25", opponent="Miami Heat", game_event_id=3),
        ]
    )

    by_season = filter_shots(shots, season="2024-25")
    assert len(by_season) == 2

    by_opponent = filter_shots(shots, season="2024-25", opponent="Miami Heat")
    assert len(by_opponent) == 1
    assert by_opponent.iloc[0]["game_event_id"] == 3

    by_range = filter_shots(shots, date_from="2023-12-01", date_to="2024-01-15")
    assert len(by_range) == 1
    assert by_range.iloc[0]["game_event_id"] == 2


def test_filter_shots_made_only_and_last_n_games():
    shots = pd.DataFrame(
        [
            _shot(game_id="G1", game_date="2024-01-01", shot_made=True, game_event_id=1),
            _shot(game_id="G1", game_date="2024-01-01", shot_made=False, game_event_id=2),
            _shot(game_id="G2", game_date="2024-01-03", shot_made=True, game_event_id=3),
            _shot(game_id="G3", game_date="2024-01-05", shot_made=True, game_event_id=4),
        ]
    )

    made_only = filter_shots(shots, made_only=True)
    assert len(made_only) == 3

    last_game = filter_shots(shots, last_n_games=1)
    assert set(last_game["game_id"]) == {"G3"}

    last_two_games = filter_shots(shots, last_n_games=2)
    assert set(last_two_games["game_id"]) == {"G2", "G3"}


def test_filter_shots_first_n_games():
    shots = pd.DataFrame(
        [
            _shot(game_id="G1", game_date="2024-01-01", game_event_id=1),
            _shot(game_id="G2", game_date="2024-01-03", game_event_id=2),
            _shot(game_id="G3", game_date="2024-01-05", game_event_id=3),
        ]
    )

    first_game = filter_shots(shots, first_n_games=1)
    assert set(first_game["game_id"]) == {"G1"}

    first_two_games = filter_shots(shots, first_n_games=2)
    assert set(first_two_games["game_id"]) == {"G1", "G2"}


def test_compare_periods_aligns_zones_from_both_sides():
    shots_a = pd.DataFrame(
        [
            _shot(shot_zone_basic="Restricted Area", shot_made=True, game_event_id=1),
            _shot(shot_zone_basic="Restricted Area", shot_made=True, game_event_id=2),
        ]
    )
    shots_b = pd.DataFrame(
        [
            _shot(shot_zone_basic="Restricted Area", shot_made=False, game_event_id=1),
            _shot(shot_zone_basic="Mid-Range", shot_type="2PT Field Goal", shot_made=True, game_event_id=2),
        ]
    )

    comparison = compare_periods(shots_a, shots_b).set_index("shot_zone_basic")

    rim = comparison.loc["Restricted Area"]
    assert rim["attempts_a"] == 2
    assert rim["attempts_b"] == 1
    assert rim["fg_pct_a"] == 1.0
    assert rim["fg_pct_b"] == 0.0

    midrange = comparison.loc["Mid-Range"]
    assert midrange["attempts_a"] == 0
    assert midrange["attempts_b"] == 1
    assert np.isnan(midrange["fg_pct_a"])


def test_opponent_zone_defense_aggregates_by_defending_team_and_zone():
    shots = pd.DataFrame(
        [
            _shot(opponent="Miami Heat", shot_zone_basic="Restricted Area", shot_made=True, game_event_id=1),
            _shot(opponent="Miami Heat", shot_zone_basic="Restricted Area", shot_made=False, game_event_id=2),
            _shot(opponent="Miami Heat", shot_zone_basic="Mid-Range", shot_made=True, game_event_id=3),
            _shot(opponent="New York Knicks", shot_zone_basic="Restricted Area", shot_made=True, game_event_id=4),
        ]
    )

    defense = opponent_zone_defense(shots).set_index(["defending_team", "shot_zone_basic"])

    heat_rim = defense.loc[("Miami Heat", "Restricted Area")]
    assert heat_rim["attempts_against"] == 2
    assert heat_rim["makes_against"] == 1
    assert heat_rim["fg_pct_against"] == 0.5

    knicks_rim = defense.loc[("New York Knicks", "Restricted Area")]
    assert knicks_rim["attempts_against"] == 1
    assert knicks_rim["fg_pct_against"] == 1.0


def test_opponent_zone_defense_empty_input_returns_empty_frame():
    defense = opponent_zone_defense(pd.DataFrame())
    assert defense.empty
    assert "defending_team" in defense.columns


def test_compare_to_opponent_defense_merges_and_flags_missing_sample_as_nan():
    player_shots = pd.DataFrame(
        [
            _shot(shot_zone_basic="Restricted Area", shot_made=True, game_event_id=1),
            _shot(shot_zone_basic="Mid-Range", shot_type="2PT Field Goal", shot_made=True, game_event_id=2),
        ]
    )
    player_summary = zone_summary(player_shots)

    league_shots = pd.DataFrame(
        [
            _shot(opponent="Miami Heat", shot_zone_basic="Restricted Area", shot_made=False, game_event_id=1),
            _shot(opponent="Miami Heat", shot_zone_basic="Restricted Area", shot_made=False, game_event_id=2),
        ]
    )
    defense = opponent_zone_defense(league_shots)

    compared = compare_to_opponent_defense(player_summary, defense, "Miami Heat").set_index(
        "shot_zone_basic"
    )

    rim = compared.loc["Restricted Area"]
    assert rim["fg_pct_against"] == 0.0
    assert rim["diff_points_per_shot_vs_opponent"] == rim["points_per_shot"] - 0.0

    # Meia distância: Miami Heat não tem nenhum arremesso registrado contra ali —
    # sem amostra, não "impenetrável" (NaN, não zero).
    midrange = compared.loc["Mid-Range"]
    assert np.isnan(midrange["fg_pct_against"])
    assert np.isnan(midrange["diff_points_per_shot_vs_opponent"])
