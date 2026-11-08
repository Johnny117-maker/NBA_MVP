"""Auditoria local e somente leitura; não publica modelos nem altera o histórico de treino."""

from __future__ import annotations

import argparse
import gc
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features import engineer_features  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.model import (  # noqa: E402
    SCORE_MODEL_VERSION,
    _relative_features,
    build_features,
    build_score_features,
    train_models,
)
from src.player_features import add_opponent_context, add_rolling_features  # noqa: E402
from src.player_metrics import (  # noqa: E402
    add_advanced_rate_metrics,
    add_efficiency_metrics,
    add_per36_rates,
)
from src.player_model import (  # noqa: E402
    _temporal_train_test_split,
    predict_from_features,
    train_player_models,
)
from src.shot_model import add_zone_model_features  # noqa: E402


def coverage_and_logs(connection: sqlite3.Connection, as_of: str) -> dict:
    result: dict = {"coverage": {}, "last_recorded_training": {}}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("games", "player_game_stats", "player_shots"):
        if table in tables:
            count, first, last = connection.execute(
                f"SELECT COUNT(*), MIN(game_date), MAX(game_date) FROM {table} WHERE game_date < ?", (as_of,)
            ).fetchone()
            result["coverage"][table] = {"rows": count, "first_game": first, "last_game": last}
    if "model_training_log" in tables:
        for kind in ("team", "player", "zone"):
            row = connection.execute(
                "SELECT trained_at, n_games, metrics FROM model_training_log "
                "WHERE model_type=? ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
            if row:
                result["last_recorded_training"][kind] = {
                    "recorded_at": row[0],
                    "rows": row[1],
                    "metrics": json.loads(row[2]),
                }
    result["input_quality"] = {}
    if "team_advanced_stats" in tables:
        count = connection.execute(
            "SELECT COUNT(*) FROM team_advanced_stats a JOIN games g ON a.game_id=g.game_id "
            "WHERE g.game_date < ?",
            (as_of,),
        ).fetchone()[0]
        result["input_quality"]["official_team_rating_rows"] = count
        result["input_quality"]["team_game_rows"] = 2 * result["coverage"]["games"]["rows"]
    if "player_game_stats" in tables:
        result["input_quality"]["known_starter_rows"] = connection.execute(
            "SELECT COUNT(*) FROM player_game_stats WHERE game_date < ? AND is_starter IS NOT NULL",
            (as_of,),
        ).fetchone()[0]
    return result


def team_audit(connection: sqlite3.Connection, as_of: str) -> tuple[dict, pd.DataFrame]:
    raw = pd.read_sql_query(
        "SELECT * FROM games WHERE game_date < ? ORDER BY game_date", connection, params=(as_of,)
    )
    advanced = pd.read_sql_query("SELECT * FROM team_advanced_stats", connection)
    games = engineer_features(raw, advanced)
    score_features = build_score_features(games)
    folds = []
    for season in sorted(games["season"].unique())[-3:]:
        test = games[games["season"].eq(season)]
        cutoff = test["game_date"].min()
        train = games[games["game_date"] < cutoff]
        if len(train) < 100:
            continue
        bundle = train_models(train)
        x_test = build_features(test)
        probability = bundle.win_model.predict_proba(x_test)[:, 1]
        # Modelo anterior (logística sobre cinco diferenças), como referência fixa.
        legacy_train, legacy_test = _relative_features(train), _relative_features(test)
        legacy_probability = (
            make_pipeline(StandardScaler(), LogisticRegression(max_iter=1_000, random_state=42))
            .fit(legacy_train, train["home_win"].astype(int))
            .predict_proba(legacy_test)[:, 1]
        )
        home_rate = float(train["home_win"].mean())
        row = {
            "season": season,
            "train_rows": len(train),
            "test_rows": len(test),
            "train_end": str(train["game_date"].max().date()),
            "test_start": str(test["game_date"].min().date()),
            "test_end": str(test["game_date"].max().date()),
            "accuracy": float(accuracy_score(test["home_win"], probability >= 0.5)),
            "always_home_accuracy": float(test["home_win"].mean()),
            "brier": float(brier_score_loss(test["home_win"], probability)),
            "constant_home_rate_brier": float(
                brier_score_loss(test["home_win"], np.full(len(test), home_rate))
            ),
            "log_loss": float(log_loss(test["home_win"], probability, labels=[0, 1])),
            "legacy_accuracy": float(accuracy_score(test["home_win"], legacy_probability >= 0.5)),
            "legacy_brier": float(brier_score_loss(test["home_win"], legacy_probability)),
            "legacy_log_loss": float(log_loss(test["home_win"], legacy_probability, labels=[0, 1])),
        }
        calibration = pd.DataFrame({"predicted": probability, "actual": test["home_win"].to_numpy()})
        calibration["bucket"] = np.minimum((probability * 10).astype(int), 9)
        row["calibration_bins"] = [
            {
                "bin": int(bucket),
                "count": len(part),
                "mean_probability": float(part["predicted"].mean()),
                "home_win_frequency": float(part["actual"].mean()),
            }
            for bucket, part in calibration.groupby("bucket")
        ]
        scores = bundle.predict_scores(x_test, score_features.loc[test.index])
        for side in ("home", "away"):
            target = f"{side}_points"
            predicted = scores[target]
            legacy = (
                make_pipeline(StandardScaler(), Ridge(alpha=2.0))
                .fit(legacy_train, train[target])
                .predict(legacy_test)
            )
            baseline = score_features.loc[test.index, f"{side}_points_avg10"]
            row[f"{side}_mae"] = float(mean_absolute_error(test[target], predicted))
            row[f"{side}_recent_mean_mae"] = float(mean_absolute_error(test[target], baseline))
            row[f"{side}_relative_features_legacy_mae"] = float(
                mean_absolute_error(test[target], legacy)
            )
        folds.append(row)
    return {
        "method": "Expanding train; complete seasons as outer tests; no parameter search",
        "score_model_version": SCORE_MODEL_VERSION,
        "comparison": (
            "Production absolute/recent score features vs legacy five relative features; "
            "causal priors in both"
        ),
        "folds": folds,
    }, games


def leakage_probes() -> dict:
    raw = pd.DataFrame(
        [
            {
                "game_id": str(i),
                "game_date": f"2025-01-{i:02d}",
                "season": "2024-25",
                "home_team": "A",
                "away_team": "B",
                "home_points": 110,
                "away_points": 100,
            }
            for i in (1, 2, 3)
        ]
    )
    future = raw.tail(1).copy()
    future[["game_id", "game_date", "home_points", "away_points"]] = ["future", "2026-01-01", 500, 400]
    initial = engineer_features(raw).iloc[0]
    extended = engineer_features(pd.concat([raw, future])).iloc[0]
    shots = pd.DataFrame(
        [
            {
                "player_id": 1,
                "player_name": "Probe",
                "game_id": str(day),
                "game_date": pd.Timestamp(f"2025-01-{day:02d}"),
                "season": "2024-25",
                "team_name": "A",
                "opponent": "B",
                "shot_attempted": 1,
                "shot_made": attempt % 2,
                "shot_type": "2PT Field Goal",
                "shot_zone_basic": "Restricted Area",
            }
            for day in (1, 2, 3)
            for attempt in range(10)
        ]
    )
    future_shots = shots[shots["game_id"].eq("3")].copy()
    future_shots["game_id"] = "future"
    future_shots["game_date"] = pd.Timestamp("2026-01-01")
    future_shots["shot_made"] = 1
    left = add_zone_model_features(shots).iloc[0]
    right = add_zone_model_features(pd.concat([shots, future_shots])).iloc[0]
    return {
        "method": "Append a future game; the first game's pregame features must not change",
        "team": {
            "feature": "home_off_rating",
            "before": float(initial["home_off_rating"]),
            "after_appending_future": float(extended["home_off_rating"]),
        },
        "zone": {
            "feature": "fgpct_avg10_Restricted Area",
            "before": float(left["fgpct_avg10_Restricted Area"]),
            "after_appending_future": float(right["fgpct_avg10_Restricted Area"]),
        },
    }


def zone_split_audit(connection: sqlite3.Connection, as_of: str) -> dict:
    rows = pd.read_sql_query(
        "SELECT game_date, player_id, game_id FROM player_shots WHERE game_date < ? "
        "GROUP BY game_date, player_id, game_id ORDER BY game_date",
        connection,
        params=(as_of,),
    )
    dates = rows["game_date"]
    boundaries = [int(len(rows) * 0.8), *np.linspace(60, len(rows), 6, dtype=int)[1:-1].tolist()]
    return {
        "player_game_rows": len(rows),
        "boundaries": [
            {
                "row": boundary,
                "train_last_date": str(dates.iloc[boundary - 1]),
                "test_first_date": str(dates.iloc[boundary]),
                "same_day_on_both_sides": bool(dates.iloc[boundary - 1] == dates.iloc[boundary]),
            }
            for boundary in boundaries
            if 0 < boundary < len(rows)
        ],
        "method": "Dates at current 80% row split and five-fold row boundaries; not a fresh zone backtest",
    }


def player_audit(connection: sqlite3.Connection, team_games: pd.DataFrame, as_of: str, max_rows: int) -> dict:
    dates = pd.read_sql_query(
        "SELECT game_date, COUNT(*) AS n FROM player_game_stats WHERE game_date < ? "
        "GROUP BY game_date ORDER BY game_date DESC",
        connection,
        params=(as_of,),
    )
    dates = dates[dates["n"].cumsum().le(max_rows)]
    if dates.empty:
        raise ValueError("Nenhuma data completa cabe no limite de linhas.")
    raw = pd.read_sql_query(
        "SELECT * FROM player_game_stats WHERE game_date >= ? AND game_date < ? ORDER BY game_date",
        connection,
        params=(dates["game_date"].min(), as_of),
    )
    raw["game_date"] = pd.to_datetime(raw["game_date"])
    raw["is_home"] = raw["is_home"].astype(bool)
    player_games = add_advanced_rate_metrics(add_per36_rates(add_efficiency_metrics(raw)))
    del raw
    features = add_opponent_context(add_rolling_features(player_games), team_games)
    del player_games
    train, test = _temporal_train_test_split(features)
    test = test[test["minutes"] > 0]
    print(f"Jogadores: treino={len(train)}, teste={len(test)}; amostra total={len(features)}", flush=True)
    bundle = train_player_models(train)
    predicted = predict_from_features(bundle, test)
    metrics = {}
    for stat in ("minutes", "pts", "reb", "ast"):
        result = {"model_mae": float(mean_absolute_error(test[stat], predicted[stat]))}
        if stat == "minutes":
            result["recent_mean_mae"] = float(mean_absolute_error(test[stat], test["minutes_avg5"]))
        else:
            for label, values in (
                (
                    "season_rate_with_predicted_minutes_mae",
                    test[f"prev_season_{stat}_per_min"] * predicted["minutes"],
                ),
                (
                    "recent_rate_with_predicted_minutes_mae",
                    test[f"{stat}_per_min_avg5"] * predicted["minutes"],
                ),
                ("recent_rate_with_recent_minutes_mae", test[f"{stat}_per_min_avg5"] * test["minutes_avg5"]),
            ):
                result[label] = float(mean_absolute_error(test[stat], values.clip(lower=0)))
        metrics[stat] = result
    return {
        "method": "One outer holdout by complete dates; training window limited as in daily picks; minutes>0",
        "sample_rows": len(features),
        "train_rows": len(train),
        "test_rows": len(test),
        "train_start": str(train["game_date"].min().date()),
        "train_end": str(train["game_date"].max().date()),
        "test_start": str(test["game_date"].min().date()),
        "test_end": str(test["game_date"].max().date()),
        "metrics": metrics,
    }


def historical_report_audit(path: Path) -> dict:
    if not path.exists():
        return {"available": False}
    cols = [
        "fold",
        "game_date",
        "confidence",
        "actual_pts",
        "predicted_pts",
        "minutes_absolute_error",
        "pts_absolute_error",
        "reb_absolute_error",
        "ast_absolute_error",
    ]
    frame = pd.read_csv(path, usecols=cols, parse_dates=["game_date"])
    folds = []
    for fold, rows in frame.groupby("fold"):
        folds.append(
            {
                "fold": int(fold),
                "rows": len(rows),
                "start": str(rows["game_date"].min().date()),
                "end": str(rows["game_date"].max().date()),
                **{
                    f"{stat}_mae": float(rows[f"{stat}_absolute_error"].mean())
                    for stat in ("minutes", "pts", "reb", "ast")
                },
            }
        )
    return {
        "available": True,
        "path": str(path),
        "rows": len(frame),
        "folds": folds,
        "warning": "Existing CSV: not a fresh evaluation, no model fingerprint and no interval bounds",
    }


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/nba.db"))
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument(
        "--players", action="store_true", help="Executa um teste novo e limitado de jogadores."
    )
    parser.add_argument("--max-player-rows", type=int, default=40_000)
    parser.add_argument("--output", type=Path, default=Path("reports/model_audit.json"))
    args = parser.parse_args()
    date.fromisoformat(args.as_of)
    uri = args.db.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        result = {"as_of": args.as_of, **coverage_and_logs(connection, args.as_of)}
        result["leakage_probes"] = leakage_probes()
        result["zone_validation_splits"] = zone_split_audit(connection, args.as_of)
        result["teams"], team_games = team_audit(connection, args.as_of)
        if args.players:
            gc.collect()
            result["players_fresh_holdout"] = player_audit(
                connection, team_games, args.as_of, args.max_player_rows
            )
    result["historical_player_report"] = historical_report_audit(
        Path("reports/player_backtest_predictions.csv")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Auditoria salva em {args.output}", flush=True)


if __name__ == "__main__":
    main()
