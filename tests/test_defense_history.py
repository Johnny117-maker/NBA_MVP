from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.history_normalize import game_phase, normalize_pbp_zones, normalize_team_boxes
from src.history_sources import BASE, select_assets
from src.history_store import connect_history
from src.player_defense_fit import DIMENSIONS, defense_context, fit_summary
from src.player_matchups import MATCHUP_COLUMNS, STATS, defender_summary, normalize_matchups
from src.store import init_db
from src.team_defense import REGULAR, defense_tables


def box(game_id, day, team, opponent, points=100, paint=40, fg3a=30, fg3m=10):
    return dict(
        season="2024-25",
        phase=REGULAR,
        game_id=game_id,
        game_date=day,
        team=team,
        opponent=opponent,
        is_home=int(team == "BOS"),
        points=points,
        opponent_points=100,
        fgm=40,
        fga=90,
        fg3m=fg3m,
        fg3a=fg3a,
        ftm=10,
        fta=20,
        oreb=10,
        dreb=30,
        ast=20,
        tov=10,
        stl=5,
        blk=5,
        paint=paint,
        source="fixture",
    )


def save_boxes(path, rows):
    init_db(path)
    with connect_history(path) as db:
        columns = list(rows[0])
        db.executemany(
            f"INSERT INTO team_boxes ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [tuple(row[col] for col in columns) for row in rows],
        )


def test_catalog_only_accepts_known_public_parquet_assets_without_path_traversal():
    tag = "nba_stats_leaguedash"
    valid = {"name": "team_master_2027.parquet", "size": 100, "url": f"{BASE}/{tag}/team_master_2027.parquet"}
    bad = [
        {**valid, "name": "../team_master_2027.parquet"},
        {**valid, "url": "https://example.com/private"},
        {**valid, "name": "team_master_2030.parquet"},
        {**valid, "size": 200_000_000},
    ]
    result = select_assets(
        [{"tag": tag, "files": [valid, *bad]}, {"tag": "other", "files": [valid]}], 2022, 2027
    )
    assert len(result) == 1
    assert result[0].name == valid["name"]


def test_defense_rates_are_weighted_and_incomplete_zones_do_not_look_complete(tmp_path):
    path = tmp_path / "nba.db"
    rows = [
        box("g1", "2025-01-01", "BOS", "NYK"),
        box("g1", "2025-01-01", "NYK", "BOS", fg3a=1, fg3m=1),
        box("g2", "2025-01-03", "BOS", "NYK"),
        box("g2", "2025-01-03", "NYK", "BOS", fg3a=9, fg3m=0),
    ]
    save_boxes(path, rows)
    with connect_history(path) as db:
        db.execute(
            "INSERT INTO defense_zones VALUES (?,?,?,?,?,?,?,?,?)",
            ("2024-25", REGULAR, "g1", "2025-01-01", "BOS", "Aro (<6 pés)", 5, 3, "fixture"),
        )
    summary, zones = defense_tables(path, "2024-25")
    observed = summary.loc[summary.team.eq("BOS")].iloc[0]
    assert observed.opp_3p_pct == pytest.approx(0.1)
    assert observed.opp_3pa == 5
    assert observed.zone_games == 0
    assert np.isnan(observed.rim_fg_pct)
    assert np.isnan(observed.tracking_dfg_pct)
    assert not zones.empty


def test_official_drtg_only_applies_to_matching_full_phase(tmp_path):
    path = tmp_path / "nba.db"
    save_boxes(path, [box("g1", "2025-01-01", "BOS", "NYK"), box("g1", "2025-01-01", "NYK", "BOS")])
    with connect_history(path) as db:
        db.execute(
            "INSERT INTO team_seasons VALUES (?,?,?,?,?,?)",
            (
                "2024-25",
                REGULAR,
                "BOS",
                json.dumps({"gp": 1, "adv_def_rating": 111, "misc_opp_pts_paint": 42}),
                "fixture",
                "2025-01-02",
            ),
        )
    full, _ = defense_tables(path, "2024-25")
    recent, _ = defense_tables(path, "2024-25", last_n=10)
    assert full.loc[full.team.eq("BOS"), "drtg"].iloc[0] == 111
    assert full.loc[full.team.eq("BOS"), "paint_allowed"].iloc[0] == 42
    assert recent.loc[recent.team.eq("BOS"), "drtg_method"].iloc[0].startswith("Estimado")


def test_missing_coordinates_and_free_throws_never_become_rim_attempts():
    base = dict(
        game_id="0022400001",
        action_number=1,
        is_field_goal=1,
        team_tricode="BOS",
        person_id=1,
        x_legacy=0,
        y_legacy=20,
        shot_result="Made",
        shot_value=2,
    )
    frame = pd.DataFrame(
        [
            base,
            {**base, "action_number": 2, "x_legacy": np.nan},
            {**base, "action_number": 3, "is_field_goal": 0},
            base,
        ]
    )
    schedule = pd.DataFrame(
        [
            dict(
                game_id="0022400001",
                game_date="2025-01-01",
                home_team_abbreviation="BOS",
                away_team_abbreviation="NYK",
            )
        ]
    )
    zones, shots = normalize_pbp_zones(frame, schedule, 2025)
    assert len(shots) == 1
    assert zones.attempts.sum() == 1
    assert zones.team.iloc[0] == "NYK"
    assert game_phase("0042400001") == "Playoffs"
    assert game_phase("0052400001") == "Play-in"


def test_matchup_summary_preserves_fractional_possessions_and_weights_shooting():
    rows = pd.DataFrame(
        [
            dict(
                def_id=2,
                def_name="Defender",
                def_position="G",
                game_id="g1",
                seconds=30,
                possessions=0.5,
                points=2,
                fgm=1,
                fga=1,
                fg3m=0,
                fg3a=0,
                switches=0,
                turnovers=0,
            ),
            dict(
                def_id=2,
                def_name="Defender",
                def_position="G",
                game_id="g2",
                seconds=90,
                possessions=9.5,
                points=0,
                fgm=0,
                fga=9,
                fg3m=0,
                fg3a=0,
                switches=1,
                turnovers=1,
            ),
        ]
    )
    row = defender_summary(rows).iloc[0]
    assert row.games == 2
    assert row.minutes == 2
    assert row.possessions == 10
    assert row.fg_pct == pytest.approx(0.1)
    assert np.isnan(row.fg3_pct)


def test_matchup_parser_rejects_self_attribution_and_invalid_counts():
    row = dict(
        game_id="0022400001",
        off_person_id=1,
        def_person_id=2,
        off_first_name="Attack",
        off_family_name="One",
        def_first_name="Defend",
        def_family_name="Two",
        off_team_id=1610612738,
        matchup_minutes="1:30",
        **{field: 0 for field in STATS.values()},
    )
    row["partial_possessions"] = 0.7
    schedule = pd.DataFrame(
        [dict(game_id="0022400001", game_date="2025-01-01", home_team_id=1610612738, away_team_id=1610612752)]
    )
    frame = pd.DataFrame(
        [row, {**row, "def_person_id": 1}, {**row, "def_person_id": 3, "matchup_field_goals_made": 2}]
    )
    parsed = normalize_matchups(frame, schedule, 2025)
    assert len(parsed) == 1
    assert parsed.off_team.iloc[0] == "BOS"
    assert parsed.def_team.iloc[0] == "NYK"
    assert parsed.possessions.iloc[0] == 0.7
    assert parsed.seconds.iloc[0] == 90
    assert list(parsed) == MATCHUP_COLUMNS


def test_profiles_do_not_change_when_the_current_or_future_game_changes():
    rows = []
    for i in range(9):
        day = f"2025-01-{i + 1:02d}"
        rows.extend(
            [box(f"g{i}", day, "BOS", "NYK", paint=30 + i), box(f"g{i}", day, "NYK", "BOS", paint=55 - i)]
        )
    original = pd.DataFrame(rows)
    changed = original.copy()
    changed.loc[changed.game_date.ge("2025-01-07"), ["points", "paint", "fg3m"]] = 999
    before = defense_context(original)
    after = defense_context(changed)
    pd.testing.assert_frame_equal(
        before.loc[before.game_date.le("2025-01-07")].reset_index(drop=True),
        after.loc[after.game_date.le("2025-01-07")].reset_index(drop=True),
    )
    assert set(before.loc[before.game_date.eq("2025-01-05"), "paint_profile"]) == {"Sem amostra prévia"}


def test_fit_uses_complementary_games_and_keeps_equal_production_uncertain():
    logs = []
    context = []
    for i in range(20):
        day = f"2025-01-{i + 1:02d}"
        logs.append(dict(game_id=f"g{i}", game_date=day, opponent="BOS", minutes=20, pts=20, fgm=5, fga=10))
        context.append(
            dict(
                game_date=pd.Timestamp(day),
                team="BOS",
                season="2024-25",
                phase=REGULAR,
                **{key: "Menor concessão" if i < 10 else "Maior concessão" for key in DIMENSIONS},
            )
        )
    result, _ = fit_summary(pd.DataFrame(logs), pd.DataFrame(context), "2024-25", REGULAR)
    assert len(result) == 6
    assert result.games.eq(10).all() and result.comparison_games.eq(10).all()
    assert result.difference_low.eq(0).all() and result.difference_high.eq(0).all()
    assert result.interpretation.eq("Diferença incerta").all()


def test_normalized_team_boxes_preserve_unavailable_paint_and_phase():
    common = dict(
        game_id=22,
        game_date="2025-01-01",
        season_type=3,
        field_goals_made=40,
        field_goals_attempted=90,
        three_point_field_goals_made=10,
        three_point_field_goals_attempted=30,
    )
    frame = pd.DataFrame(
        [
            {
                **common,
                "team_abbreviation": "BOS",
                "opponent_team_abbreviation": "NYK",
                "team_home_away": "home",
                "team_score": 100,
                "opponent_team_score": 110,
            },
            {
                **common,
                "team_abbreviation": "NYK",
                "opponent_team_abbreviation": "BOS",
                "team_home_away": "away",
                "team_score": 110,
                "opponent_team_score": 100,
            },
        ]
    )
    normalized = normalize_team_boxes(frame, {("2025-01-01", "BOS", "NYK"): "0042400001"}, 2025)
    assert len(normalized) == 2
    assert normalized.phase.eq("Playoffs").all()
    assert normalized.paint.isna().all()
