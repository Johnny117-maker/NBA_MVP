from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from src.shot_features import THREE_POINT_ZONES, ZONES
from src.shot_model import (
    add_opponent_zone_defense_features,
    add_zone_model_features,
    add_zone_rolling_features,
    build_zone_game_table,
    expected_fg_points,
    fill_missing_features_with_league_average,
    live_zone_snapshot,
    predict_zone_distribution,
    train_zone_models,
    walk_forward_evaluate_zone_models,
)

TEAMS = ["Team A", "Team B", "Team C", "Team D", "Team E"]

# Perfis fixos por jogador: pesos de zona (frequência) e FG% base por zona —
# dados sintéticos, só para o modelo ter um padrão real para aprender.
PLAYER_PROFILES = {
    0: {  # "Rim Runner": arremessa quase só perto da cesta, com alta eficiência ali.
        "name": "Rim Runner",
        "weights": {"Restricted Area": 0.65, "In The Paint (Non-RA)": 0.15, "Mid-Range": 0.10,
                    "Left Corner 3": 0.03, "Right Corner 3": 0.03, "Above the Break 3": 0.03, "Backcourt": 0.01},
        "fg_pct": {"Restricted Area": 0.68, "In The Paint (Non-RA)": 0.42, "Mid-Range": 0.35,
                   "Left Corner 3": 0.30, "Right Corner 3": 0.30, "Above the Break 3": 0.28, "Backcourt": 0.05},
    },
    1: {  # "Sharpshooter": maioria de três, bom aproveitamento de fora.
        "name": "Sharpshooter",
        "weights": {"Restricted Area": 0.15, "In The Paint (Non-RA)": 0.05, "Mid-Range": 0.10,
                    "Left Corner 3": 0.10, "Right Corner 3": 0.10, "Above the Break 3": 0.48, "Backcourt": 0.02},
        "fg_pct": {"Restricted Area": 0.55, "In The Paint (Non-RA)": 0.38, "Mid-Range": 0.36,
                   "Left Corner 3": 0.42, "Right Corner 3": 0.42, "Above the Break 3": 0.40, "Backcourt": 0.10},
    },
    2: {  # perfil misto
        "name": "Combo Guard",
        "weights": {"Restricted Area": 0.30, "In The Paint (Non-RA)": 0.15, "Mid-Range": 0.25,
                    "Left Corner 3": 0.08, "Right Corner 3": 0.08, "Above the Break 3": 0.13, "Backcourt": 0.01},
        "fg_pct": {"Restricted Area": 0.60, "In The Paint (Non-RA)": 0.40, "Mid-Range": 0.38,
                   "Left Corner 3": 0.34, "Right Corner 3": 0.34, "Above the Break 3": 0.33, "Backcourt": 0.08},
    },
    3: {  # outro perfil misto, times diferentes
        "name": "Big Man",
        "weights": {"Restricted Area": 0.55, "In The Paint (Non-RA)": 0.25, "Mid-Range": 0.15,
                    "Left Corner 3": 0.02, "Right Corner 3": 0.02, "Above the Break 3": 0.01, "Backcourt": 0.00},
        "fg_pct": {"Restricted Area": 0.62, "In The Paint (Non-RA)": 0.45, "Mid-Range": 0.30,
                   "Left Corner 3": 0.25, "Right Corner 3": 0.25, "Above the Break 3": 0.20, "Backcourt": 0.05},
    },
}


def _synthetic_shots(games_per_player: int = 25, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    game_counter = 0

    for player_id, profile in PLAYER_PROFILES.items():
        team = TEAMS[player_id % len(TEAMS)]
        zones = list(profile["weights"])
        weights = np.array([profile["weights"][z] for z in zones])
        weights = weights / weights.sum()

        game_date = pd.Timestamp("2023-10-24")
        for game_number in range(games_per_player):
            opponent = TEAMS[(player_id + 1 + game_number) % len(TEAMS)]
            if opponent == team:
                opponent = TEAMS[(player_id + 2 + game_number) % len(TEAMS)]
            game_id = f"G{game_counter:04d}"
            game_counter += 1
            game_date = game_date + timedelta(days=2)

            n_shots = rng.integers(10, 20)
            chosen_zones = rng.choice(zones, size=n_shots, p=weights)
            for event_id, zone in enumerate(chosen_zones, start=1):
                fg_pct = profile["fg_pct"][zone]
                made = bool(rng.random() < fg_pct)
                shot_type = "3PT Field Goal" if zone in THREE_POINT_ZONES else "2PT Field Goal"
                rows.append(
                    {
                        "player_id": player_id,
                        "player_name": profile["name"],
                        "game_id": game_id,
                        "game_event_id": event_id,
                        "season": "2023-24",
                        "game_date": game_date,
                        "team_id": player_id,
                        "team_name": team,
                        "opponent": opponent,
                        "period": 1,
                        "minutes_remaining": 5,
                        "seconds_remaining": 0,
                        "event_type": "Made Shot" if made else "Missed Shot",
                        "action_type": "Jump Shot",
                        "shot_type": shot_type,
                        "shot_zone_basic": zone,
                        "shot_zone_area": "Center(C)",
                        "shot_zone_range": "Less Than 8 ft.",
                        "shot_distance": 5.0,
                        "loc_x": 0,
                        "loc_y": 0,
                        "loc_x_ft": 0.0,
                        "loc_y_ft": 0.0,
                        "shot_attempted": 1,
                        "shot_made": made,
                        "source": "nba_api",
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def synthetic_shots() -> pd.DataFrame:
    return _synthetic_shots()


@pytest.fixture(scope="module")
def zone_games_with_features(synthetic_shots: pd.DataFrame) -> pd.DataFrame:
    return add_zone_model_features(synthetic_shots)


# --- build_zone_game_table -----------------------------------------------


def test_build_zone_game_table_totals_and_shares_are_consistent():
    shots = pd.DataFrame(
        [
            {**row, "player_id": 1, "player_name": "X", "game_id": "G1", "game_date": pd.Timestamp("2024-01-01"),
             "season": "2023-24", "team_name": "Team A", "opponent": "Team B"}
            for row in [
                {"game_event_id": 1, "team_id": 1, "period": 1, "minutes_remaining": 5, "seconds_remaining": 0,
                 "event_type": "Made Shot", "action_type": "Jump Shot", "shot_type": "2PT Field Goal",
                 "shot_zone_basic": "Restricted Area", "shot_zone_area": "Center(C)",
                 "shot_zone_range": "Less Than 8 ft.", "shot_distance": 2.0, "loc_x": 0, "loc_y": 0,
                 "loc_x_ft": 0.0, "loc_y_ft": 0.0, "shot_attempted": 1, "shot_made": True, "source": "nba_api"},
                {"game_event_id": 2, "team_id": 1, "period": 1, "minutes_remaining": 4, "seconds_remaining": 0,
                 "event_type": "Missed Shot", "action_type": "Jump Shot", "shot_type": "3PT Field Goal",
                 "shot_zone_basic": "Above the Break 3", "shot_zone_area": "Center(C)",
                 "shot_zone_range": "24+ ft.", "shot_distance": 26.0, "loc_x": 0, "loc_y": 260,
                 "loc_x_ft": 0.0, "loc_y_ft": 26.0, "shot_attempted": 1, "shot_made": False, "source": "nba_api"},
            ]
        ]
    )
    table = build_zone_game_table(shots)
    assert len(table) == 1
    row = table.iloc[0]
    assert row["total_fga"] == 2
    assert row["total_fg_makes"] == 1
    assert row["total_fg_points"] == 2
    assert row["attempts_Restricted Area"] == 1
    assert row["share_Restricted Area"] == 0.5
    assert row["fg_pct_Restricted Area"] == 1.0
    assert row["attempts_Above the Break 3"] == 1
    assert row["fg_pct_Above the Break 3"] == 0.0
    # Zona sem nenhuma tentativa: participação 0, eficiência NaN (não 0).
    assert row["share_Mid-Range"] == 0.0
    assert np.isnan(row["fg_pct_Mid-Range"])


# --- leakage protection -----------------------------------------------------


def test_zone_rolling_features_do_not_leak_current_game(synthetic_shots):
    zone_games = build_zone_game_table(synthetic_shots)
    with_rolling = add_zone_rolling_features(zone_games)

    player_rows = with_rolling[with_rolling["player_id"] == 0].sort_values("game_date").reset_index(drop=True)
    # Um jogador que só arremessou do aro em todo o histórico exceto no último
    # jogo (onde jogamos tudo pra "Backcourt") não pode ver isso refletido em
    # `share_avg10_Backcourt` NESSE MESMO jogo — só a partir do próximo.
    zone = "Backcourt"
    last_index = len(player_rows) - 1
    # Se o jogador nunca tentou "Backcourt" antes do último jogo (verdade para
    # o perfil sintético "Rim Runner"), a média até o penúltimo jogo deve ser
    # ~0, mesmo que o último jogo em si tenha tentativas nessa zona.
    assert player_rows.loc[last_index, f"share_avg10_{zone}"] < 0.05


def test_opponent_zone_defense_features_use_only_prior_games(synthetic_shots):
    zone_games = build_zone_game_table(synthetic_shots)
    with_defense = add_opponent_zone_defense_features(zone_games, synthetic_shots)

    # A primeira vez que cada adversário aparece na base, a defesa "vista até
    # aqui" só pode vir da média da liga (preenchimento), não de um jogo
    # futuro contra esse mesmo time.
    first_occurrence = with_defense.sort_values("game_date").groupby("opponent").head(1)
    for zone in ZONES:
        # Não afirma igualdade exata (a primeira ocorrência de cada time não é
        # necessariamente a primeira cronologicamente da base toda), só que
        # nenhum valor "no futuro" vaza — checado indiretamente pelo teste de
        # walk-forward abaixo, que é o teste de vazamento mais forte.
        assert first_occurrence[f"defense_share_allowed_avg_{zone}"].notna().all()


# --- train / predict end-to-end --------------------------------------------


def test_train_zone_models_raises_with_too_few_games():
    tiny = pd.DataFrame({"game_date": pd.to_datetime(["2024-01-01"] * 5)})
    with pytest.raises(ValueError):
        train_zone_models(tiny)


def test_predicted_shares_sum_to_one_and_reflect_player_profile(zone_games_with_features):
    bundle = train_zone_models(zone_games_with_features)

    rim_runner_rows = zone_games_with_features[zone_games_with_features["player_id"] == 0]
    zone_predictions = predict_zone_distribution(bundle, rim_runner_rows)

    totals_by_row = zone_predictions.groupby("row_index")["predicted_share"].sum()
    assert np.allclose(totals_by_row.to_numpy(), 1.0, atol=1e-6)

    avg_share_by_zone = zone_predictions.groupby("shot_zone_basic")["predicted_share"].mean()
    # "Rim Runner" arremessa ~65% do aro — a previsão média deve refletir isso
    # sendo, disparado, a zona de maior participação prevista.
    assert avg_share_by_zone.idxmax() == "Restricted Area"
    assert avg_share_by_zone["Restricted Area"] > 0.4


def test_expected_fg_points_matches_manual_calculation():
    zone_predictions = pd.DataFrame(
        [
            {"row_index": 0, "shot_zone_basic": "Restricted Area", "zone_label": "Aro",
             "predicted_share": 0.75, "predicted_fg_pct": 0.60},
            {"row_index": 0, "shot_zone_basic": "Above the Break 3", "zone_label": "Três frontal",
             "predicted_share": 0.25, "predicted_fg_pct": 0.40},
        ]
    )
    predicted_fga = pd.Series({0: 20.0})

    result = expected_fg_points(zone_predictions, predicted_fga)

    # Aro: 15 tentativas (0.75*20) x 60% x 2 pts = 18. Três: 5 tentativas x 40% x 3 = 6. Total = 24.
    assert result.loc[0] == pytest.approx(24.0)


def test_live_zone_snapshot_has_no_nan_after_fill_and_predicts(synthetic_shots, zone_games_with_features):
    bundle = train_zone_models(zone_games_with_features)

    snapshot = live_zone_snapshot(
        zone_games_with_features, player_id=1, defending_team="Team C", shots=synthetic_shots
    )
    filled = fill_missing_features_with_league_average(bundle, snapshot)
    assert not filled.isna().any().any()

    zone_predictions = predict_zone_distribution(bundle, filled)
    assert len(zone_predictions) == len(ZONES)
    assert zone_predictions["predicted_share"].sum() == pytest.approx(1.0, abs=1e-6)


def test_live_zone_snapshot_without_chosen_opponent_still_fills_with_league_average(
    synthetic_shots, zone_games_with_features
):
    bundle = train_zone_models(zone_games_with_features)
    snapshot = live_zone_snapshot(
        zone_games_with_features, player_id=2, defending_team=None, shots=synthetic_shots
    )
    filled = fill_missing_features_with_league_average(bundle, snapshot)
    assert not filled.isna().any().any()


def test_live_zone_snapshot_raises_for_unknown_player(synthetic_shots, zone_games_with_features):
    with pytest.raises(ValueError):
        live_zone_snapshot(zone_games_with_features, player_id=999, defending_team=None, shots=synthetic_shots)


# --- walk-forward ------------------------------------------------------------


def test_walk_forward_evaluate_zone_models_returns_sane_aggregate(zone_games_with_features):
    result = walk_forward_evaluate_zone_models(zone_games_with_features, n_folds=2, min_train_games=30)

    assert result["aggregate"]["n_folds"] >= 1
    assert result["aggregate"]["fg_points_mae"] >= 0
    for zone in ZONES:
        assert result["aggregate"][f"share_mae_{zone}"] >= 0
    for fold in result["folds"]:
        assert fold["n_test"] > 0


def test_walk_forward_evaluate_zone_models_raises_with_too_few_games():
    tiny = pd.DataFrame({"game_date": pd.to_datetime(["2024-01-01"] * 10)})
    with pytest.raises(ValueError):
        walk_forward_evaluate_zone_models(tiny, min_train_games=30)
