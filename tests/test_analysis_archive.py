import copy
import json
import sqlite3
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.analysis_archive import (
    apply_frozen_pregame_props,
    archive_path,
    archive_snapshot,
    connect_archive,
    create_daily_snapshots,
    highlighted_players,
    read_snapshots,
    resolve_snapshots,
    snapshot_html,
    snapshot_table,
)
from src.live_store import set_state
from src.live_types import LiveGame
from src.player_metrics import add_efficiency_metrics
from src.prop_training import FEATURES, feature_table, project_props, train_props
from src.research_feeds import collect_rim_defense, import_metrics, read_metrics
from src.research_metrics import beta_shooting, defended_rim, fit_rapm, kalman_rate, off_ball_gravity
from src.shot_quality import expected_points, train_location_quality
from src.store import init_db, upsert_games, upsert_player_games


@pytest.fixture
def research_history():
    rng = np.random.default_rng(42)
    rows = []
    for day in pd.date_range("2026-08-09", "2026-10-27"):
        for pid in range(1, 21):
            home = pid <= 10
            fgm = int(rng.integers(3, 10))
            fg3m = min(fgm, int(rng.integers(0, 4)))
            ftm = int(rng.integers(0, 4))
            rows.append(
                {
                    "game_id": day.strftime("%Y%m%d"),
                    "game_date": day,
                    "season": "2026-27",
                    "player_id": pid,
                    "player_name": f"Test Player {pid}",
                    "team": "BOS" if home else "NYK",
                    "opponent": "NYK" if home else "BOS",
                    "is_home": home,
                    "minutes": 24.0,
                    "pts": 2 * fgm + fg3m + ftm,
                    "fga": fgm + 5,
                    "fgm": fgm,
                    "fg3m": fg3m,
                    "fg3a": fg3m + 3,
                    "fta": ftm + 1,
                    "ftm": ftm,
                    "reb": 6,
                    "oreb": 2,
                    "dreb": 4,
                    "ast": int(rng.integers(1, 6)),
                    "tov": 2,
                    "stl": 1,
                    "blk": 0,
                    "pf": 2,
                }
            )
    return pd.DataFrame(rows)


def pregame():
    return LiveGame(
        "0022600100",
        "NBA",
        "2026-10-28",
        "2026-27",
        "BOS",
        "NYK",
        "pre",
        "2026-10-28T12:00:00+00:00",
        kickoff="2026-10-28T23:30:00+00:00",
    )


CAPTURE = datetime(2026, 10, 28, 16, tzinfo=UTC)


def test_automatic_scope_records_all_eligible_players_and_excludes_injuries(tmp_path, research_history):
    path = tmp_path / "nba.db"
    init_db(path)
    set_state(
        path,
        "injury_snapshot",
        {
            "source": "fixture",
            "rows": [
                {"player": "Test Player 1", "team": "BOS", "status": "Fora"},
            ],
        },
    )
    assert (
        create_daily_snapshots(path, [pregame()], research_history, now=CAPTURE, players_per_team=None) == 1
    )
    snapshot = read_snapshots(path)[0]
    assert len(snapshot["players"]) == 19
    assert "Test Player 1" not in {player["name"] for player in snapshot["players"]}
    assert snapshot["selection_scope"] == "Todos os elegíveis"


def test_new_snapshots_exclude_injuries_before_top_three_without_rewriting_old_snapshots(
    tmp_path, research_history
):
    old_path = tmp_path / "old.db"
    init_db(old_path)
    assert create_daily_snapshots(old_path, [pregame()], research_history, now=CAPTURE) == 1
    original = read_snapshots(old_path)
    player = highlighted_players(research_history, pregame()).iloc[0]
    bulletin = {
        "source": "ESPN test",
        "source_updated": CAPTURE.isoformat(),
        "rows": [
            {"player": player.player_name, "team": player.team, "status": "Fora"},
        ],
    }
    set_state(old_path, "injury_snapshot", bulletin)
    assert create_daily_snapshots(old_path, [pregame()], research_history, now=CAPTURE) == 0
    assert read_snapshots(old_path) == original
    new_path = tmp_path / "new.db"
    init_db(new_path)
    set_state(new_path, "injury_snapshot", bulletin)
    assert create_daily_snapshots(new_path, [pregame()], research_history, now=CAPTURE) == 1
    players = read_snapshots(new_path)[0]["players"]
    assert len(players) == 6
    assert player.player_name not in {entry["name"] for entry in players}


def test_first_pregame_snapshot_is_frozen_and_ticks_do_not_change_history(tmp_path, research_history):
    path = tmp_path / "nba.db"
    init_db(path)
    modified = path.stat().st_mtime_ns
    assert create_daily_snapshots(path, [pregame()], research_history, now=CAPTURE) == 1
    first = read_snapshots(path)[0]
    assert len(first["players"]) == 6
    assert all(set(p["stats"]) == {"pts", "reb", "ast"} for p in first["players"])
    assert create_daily_snapshots(path, [pregame()], research_history.assign(pts=99), now=CAPTURE) == 0
    assert read_snapshots(path)[0] == first
    assert path.stat().st_mtime_ns == modified
    with connect_archive(path) as connection, pytest.raises(sqlite3.IntegrityError, match="imutáveis"):
        connection.execute("UPDATE daily_snapshots SET captured_at='changed'")
    with connect_archive(path) as connection, pytest.raises(sqlite3.IntegrityError, match="imutáveis"):
        connection.execute("DELETE FROM daily_snapshots")
    assert archive_path(path).exists()


def test_no_retroactive_snapshot_or_same_day_training(tmp_path, research_history):
    path = tmp_path / "nba.db"
    game = pregame()
    assert create_daily_snapshots(path, [game], research_history, now=datetime(2026, 10, 29, tzinfo=UTC)) == 0
    assert create_daily_snapshots(path, [game], research_history, now=CAPTURE) == 1
    payload = read_snapshots(path)[0]
    for changed in ("captured_at", "history_end", "model"):
        invalid = copy.deepcopy(payload)
        if changed == "captured_at":
            invalid[changed] = game.kickoff
        elif changed == "history_end":
            invalid[changed] = game.day
        else:
            invalid[changed]["train_end"] = game.day
        with pytest.raises(ValueError):
            archive_snapshot(tmp_path / (changed + ".db"), invalid)


def test_temporal_features_never_use_current_or_future_game(research_history):
    original = feature_table(research_history)
    target_day = pd.Timestamp("2026-10-15")
    changed = research_history.copy()
    changed.loc[changed["game_date"].ge(target_day), ["pts", "reb", "ast", "fgm", "fga"]] = 999
    after = feature_table(changed)
    mask = original["game_date"].le(target_day)
    pd.testing.assert_frame_equal(original.loc[mask, FEATURES], after.loc[mask, FEATURES])
    with pytest.raises(ValueError, match="mesmo jogador"):
        feature_table(pd.concat([research_history, research_history.head(1)], ignore_index=True))


def test_xgboost_uses_separate_calibration_and_test_dates(research_history):
    bundle = train_props(research_history, estimators=5)
    report = bundle.manifest
    assert report["fit_end"] < report["calibration_start"] < report["test_start"] <= report["test_end"]
    assert all(0 <= value <= 1 for value in report["weights"].values())
    row = feature_table(research_history).iloc[-1]
    prediction = project_props(row, bundle)
    for stat, estimate in prediction["stats"].items():
        assert estimate["xgboost"] >= 0
        assert 0 <= estimate["under"] <= 1
        assert estimate["over"] + estimate["under"] == pytest.approx(1)
        assert 0 <= estimate["low"] <= estimate["high"]
        assert report["metrics"][stat]["ensemble_mae"] >= 0


def test_exact_game_results_are_separate_and_corrections_do_not_rewrite_forecast(tmp_path, research_history):
    path = tmp_path / "nba.db"
    init_db(path)
    create_daily_snapshots(path, [pregame()], research_history, now=CAPTURE)
    frozen = read_snapshots(path)[0]
    actual = research_history.loc[
        research_history["game_date"].eq(research_history["game_date"].max())
    ].copy()
    actual["game_id"] = "actual-target"
    actual["game_date"] = pd.Timestamp("2026-10-28")
    game = pd.DataFrame(
        [
            {
                "game_id": "actual-target",
                "game_date": "2026-10-28",
                "season": "2026-27",
                "home_team": "Boston Celtics",
                "away_team": "New York Knicks",
                "home_points": int(actual.loc[actual["team"].eq("BOS"), "pts"].sum()),
                "away_points": int(actual.loc[actual["team"].eq("NYK"), "pts"].sum()),
            }
        ]
    )
    upsert_games(game, path)
    upsert_player_games(actual, path)
    assert resolve_snapshots(path) == 6
    assert resolve_snapshots(path) == 0
    first_player = frozen["players"][0]["player_id"]
    original_points = float(actual.loc[actual["player_id"].eq(first_player), "pts"].iloc[0])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE player_game_stats SET pts=pts+1 WHERE game_id=? AND player_id=?",
            ("actual-target", first_player),
        )
    assert resolve_snapshots(path) == 1
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE player_game_stats SET pts=pts-1 WHERE game_id=? AND player_id=?",
            ("actual-target", first_player),
        )
    assert resolve_snapshots(path) == 1
    table = snapshot_table(path, "2026-10-28")
    assert (
        table.loc[table["player_id"].eq(first_player) & table["stat"].eq("pts"), "actual"].iloc[0]
        == original_points
    )
    assert read_snapshots(path)[0] == frozen


def test_print_report_escapes_external_names_and_contains_original_values(tmp_path, research_history):
    create_daily_snapshots(tmp_path / "nba.db", [pregame()], research_history, now=CAPTURE)
    saved = read_snapshots(tmp_path / "nba.db")[0]
    saved["players"][0]["name"] = "<script>alert(1)</script>"
    report = snapshot_html(saved)
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "PTS previstos" in report and saved["sha256"] in report


def test_history_supplied_with_future_rows_does_not_change_snapshot(tmp_path, research_history):
    first = tmp_path / "before.db"
    second = tmp_path / "with_future.db"
    future = research_history.tail(20).copy()
    future["game_date"] = pd.Timestamp("2026-10-28")
    future["pts"] = 1000
    create_daily_snapshots(first, [pregame()], research_history, now=CAPTURE)
    create_daily_snapshots(second, [pregame()], pd.concat([research_history, future]), now=CAPTURE)
    assert read_snapshots(first) == read_snapshots(second)


def test_pregame_opportunities_reuse_frozen_values_but_live_estimates_keep_updating(
    tmp_path, research_history
):
    path = tmp_path / "nba.db"
    create_daily_snapshots(path, [pregame()], research_history, now=CAPTURE)
    saved = read_snapshots(path)[0]
    player = saved["players"][0]
    prediction = player["stats"]["pts"]
    pre = {
        "game_key": pregame().key,
        "player_id": player["player_id"],
        "stat": "pts",
        "state": "pre",
        "probability": 0.5,
        "projected": 999,
    }
    live = {**pre, "state": "live", "projected": 42}
    rows = apply_frozen_pregame_props(path, [pre, live], "2026-10-28")
    assert rows[0]["state"] == "live" and rows[0]["projected"] == 42
    assert rows[1]["projected"] == prediction["projected"]
    assert rows[1]["snapshot_id"] == saved["id"]
    assert read_snapshots(path)[0] == saved


def test_location_quality_has_a_temporal_test_and_does_not_claim_tracking(app_db, tmp_path):
    target = tmp_path / "quality"
    report = train_location_quality(app_db, target, "2026-10-28")
    assert report["test_start"] <= report["history_end"] < "2026-10-28"
    assert report["tracking"] is False
    result = expected_points(target, distance=24, angle=30, value=3)
    assert 0 < result["make_probability"] < 1
    assert result["expected_points"] == pytest.approx(3 * result["make_probability"])


def test_bayesian_shrinkage_zero_attempts_and_dynamic_rate_are_explicit():
    assert beta_shooting(0, 0, 0.36)["mean"] == pytest.approx(0.36)
    estimate = beta_shooting(8, 10, 0.36)
    assert 0.36 < estimate["mean"] < 0.8
    assert estimate["low"] < estimate["mean"] < estimate["high"]
    assert kalman_rate([2] * 10 + [20] * 5, [30] * 15)["rate"] > kalman_rate([2] * 15, [30] * 15)["rate"]
    with pytest.raises(ValueError):
        beta_shooting(11, 10, 0.36)


def test_ast_and_turnover_ratio_are_not_ast_to_ratio(research_history):
    metrics = add_efficiency_metrics(research_history)
    row = metrics.iloc[0]
    possessions = row.fga + 0.44 * row.fta + row.ast + row.tov
    assert row.assist_ratio == pytest.approx(100 * row.ast / possessions)
    assert row.turnover_ratio == pytest.approx(100 * row.tov / possessions)
    assert row.ast_to_ratio == pytest.approx(row.ast / row.tov)


def test_rapm_uses_ten_distinct_players_and_possession_weighting():
    rng = np.random.default_rng(7)
    rows = []
    for _ in range(100):
        lineup = rng.choice(np.arange(1, 16), size=10, replace=False).tolist()
        home, away = lineup[:5], lineup[5:]
        impact = 4 * ((1 in home) - (1 in away))
        rows.append(
            {
                "home_players": json.dumps(home),
                "away_players": json.dumps(away),
                "possessions": 20,
                "points_diff": (impact + 2) * 20 / 100,
            }
        )
    stints = pd.DataFrame(rows)
    fitted = fit_rapm(stints, alpha=0.01)
    assert fitted.ratings.iloc[0]["player_id"] == 1
    assert fitted.ratings.iloc[0]["rapm"] > 3
    stints.loc[0, "home_players"] = "[1,1,2,3,4]"
    with pytest.raises(ValueError, match="dez IDs"):
        fit_rapm(stints)


def test_rim_and_gravity_require_actual_defense_and_tracking():
    assert defended_rim(4, 10, 0.6)["diff_pct"] == pytest.approx(-0.2)
    assert defended_rim(0, 0)["dfg_pct"] is None
    tracking = pd.DataFrame(
        [
            {
                "frame_id": 1,
                "player_id": 1,
                "ball_handler_id": 2,
                "x": 0,
                "y": 0,
                "defender_x": 3,
                "defender_y": 4,
                "baseline_distance": 7,
                "duration": 0.04,
            },
            {
                "frame_id": 2,
                "player_id": 1,
                "ball_handler_id": 2,
                "x": 0,
                "y": 0,
                "defender_x": 0,
                "defender_y": 3,
                "baseline_distance": 7,
                "duration": 0.04,
            },
        ]
    )
    assert off_ball_gravity(tracking).iloc[0]["gravity_local_ft"] == pytest.approx(3)
    with pytest.raises(ValueError):
        off_ball_gravity(pd.DataFrame({"pts": [20]}))


def test_external_metrics_are_available_only_after_import_and_have_producer_source(tmp_path):
    rows = pd.DataFrame(
        [
            {
                "metric": "LEBRON",
                "player_id": 2544,
                "as_of": "2026-10-27",
                "value": 2.5,
                "source": "https://www.bball-index.com/lebron-database/",
            }
        ]
    )
    path = tmp_path / "nba.db"
    assert import_metrics(path, rows, now=CAPTURE) == 1
    assert read_metrics(path, known_before=datetime(2026, 10, 27, tzinfo=UTC)).empty
    assert len(read_metrics(path, known_before=CAPTURE)) == 1
    with pytest.raises(ValueError, match="Basketball Index"):
        import_metrics(path, rows.assign(source="https://example.test/lebron"), now=CAPTURE)


def test_nba_api_defense_collector_uses_date_cutoff_and_real_attempts(tmp_path, monkeypatch):
    calls = []

    class Response:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def get_data_frames(self):
            return [pd.DataFrame([{"CLOSE_DEF_PERSON_ID": 1, "D_FGM": 4, "D_FGA": 10, "NORMAL_FG_PCT": 0.6}])]

    monkeypatch.setattr("nba_api.stats.endpoints.leaguedashptdefend.LeagueDashPtDefend", Response)
    assert collect_rim_defense(tmp_path / "nba.db", "2026-27", pd.Timestamp("2026-10-27").date()) == 1
    assert calls[0]["defense_category"] == "Less Than 6Ft"
    assert calls[0]["date_to_nullable"] == "10/27/2026"
    assert read_metrics(tmp_path / "nba.db").iloc[0]["value"] == 0.4


def test_archive_and_research_pages_open_all_modes(app_db, monkeypatch, research_history):
    monkeypatch.setattr("src.ui.archive.utc_now", lambda: CAPTURE)
    monkeypatch.setattr("src.live_types.utc_now", lambda: CAPTURE)
    create_daily_snapshots(app_db, [pregame()], research_history, now=CAPTURE)
    app = AppTest.from_file("../app.py").run(timeout=45)
    app.switch_page("pages/10_Historico_Diario.py").run(timeout=30)
    assert not app.exception
    assert any("Pontos previstos" in list(frame.value.columns) for frame in app.dataframe)
    for label in ("Previsão × resultado", "Detalhes e impressão"):
        app.segmented_control[0].set_value(label).run(timeout=30)
        assert not app.exception
    app.switch_page("pages/11_Laboratorio.py").run(timeout=30)
    for label in ("Métricas e fontes", "RAPM", "Qualidade do arremesso", "Gravity", "Player props"):
        app.segmented_control[0].set_value(label).run(timeout=30)
        assert not app.exception
