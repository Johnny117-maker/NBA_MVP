"""Visões normalizadas do acervo; fases distintas e estatísticas ausentes continuam nulas."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .history_store import connect_history, history_root, read_assets
from .live_providers import team_code
from .live_types import current_season, minutes, utc_now
from .nba_teams import TEAM_ABBREVIATION_TO_NAME

PHASES = {
    "001": "Pré-temporada",
    "002": "Temporada regular",
    "004": "Playoffs",
    "005": "Play-in",
    "006": "Final da NBA Cup",
}


def season_label(year: int) -> str:
    return f"{year - 1}-{year % 100:02d}"


def game_phase(game_id: str, fallback: int = 2) -> str:
    return PHASES.get(
        str(game_id)[:3],
        {1: "Pré-temporada", 2: "Temporada regular", 3: "Pós-temporada"}.get(fallback, "Outra fase"),
    )


def normalize_team_boxes(frame: pd.DataFrame, schedule: dict, year: int) -> pd.DataFrame:
    required = {
        "game_id",
        "game_date",
        "team_abbreviation",
        "opponent_team_abbreviation",
        "team_score",
        "opponent_team_score",
    }
    if not required.issubset(frame):
        raise ValueError("Boxscore de times sem identificação, data ou placar.")
    source = frame.copy()
    source["game_date"] = pd.to_datetime(source["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    source = source.loc[source["game_date"].notna() & source["game_date"].le(utc_now().date().isoformat())]
    source["team"] = source["team_abbreviation"].map(team_code)
    source["opponent"] = source["opponent_team_abbreviation"].map(team_code)
    source = source.loc[source["team"].ne("") & source["opponent"].ne("")].copy()
    source["is_home"] = source["team_home_away"].eq("home").astype(int)
    source["game_id"] = source.apply(
        lambda row: schedule.get(
            (
                row["game_date"],
                row["team"] if row["is_home"] else row["opponent"],
                row["opponent"] if row["is_home"] else row["team"],
            ),
            "espn:" + str(row["game_id"]),
        ),
        axis=1,
    )
    source["phase"] = [
        game_phase(gid, int(kind)) for gid, kind in zip(source["game_id"], source["season_type"], strict=True)
    ]
    source["season"] = season_label(year)
    mapping = {
        "points": "team_score",
        "opponent_points": "opponent_team_score",
        "fgm": "field_goals_made",
        "fga": "field_goals_attempted",
        "fg3m": "three_point_field_goals_made",
        "fg3a": "three_point_field_goals_attempted",
        "ftm": "free_throws_made",
        "fta": "free_throws_attempted",
        "oreb": "offensive_rebounds",
        "dreb": "defensive_rebounds",
        "ast": "assists",
        "stl": "steals",
        "blk": "blocks",
        "paint": "points_in_paint",
    }
    for target, origin in mapping.items():
        source[target] = pd.to_numeric(source[origin], errors="coerce") if origin in source else np.nan
    source["tov"] = pd.to_numeric(source.get("total_turnovers", source.get("turnovers")), errors="coerce")
    source["source"] = "ESPN / SportsDataverse"
    columns = [
        "season",
        "phase",
        "game_id",
        "game_date",
        "team",
        "opponent",
        "is_home",
        "points",
        "opponent_points",
        "fgm",
        "fga",
        "fg3m",
        "fg3a",
        "ftm",
        "fta",
        "oreb",
        "dreb",
        "ast",
        "tov",
        "stl",
        "blk",
        "paint",
        "source",
    ]
    source = source.drop_duplicates(["game_id", "team"], keep="last")
    # Partidas sem os dois lados, pontos divergentes ou arremessos impossíveis não entram nas métricas.
    pairs = source.merge(
        source[["game_id", "team", "points"]],
        left_on=["game_id", "opponent"],
        right_on=["game_id", "team"],
        suffixes=("", "_other"),
    )
    valid = pairs.loc[
        pairs["points_other"].eq(pairs["opponent_points"])
        & pairs["points"].ge(0)
        & pairs["fg3m"].le(pairs["fg3a"])
        & pairs["fgm"].le(pairs["fga"])
    ]
    return valid[columns].reset_index(drop=True)


def normalize_pbp_zones(
    frame: pd.DataFrame, schedule: pd.DataFrame, year: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {
        "game_id",
        "action_number",
        "is_field_goal",
        "team_tricode",
        "person_id",
        "x_legacy",
        "y_legacy",
        "shot_result",
        "shot_value",
    }
    if not required.issubset(frame):
        raise ValueError("PBP sem os identificadores ou coordenadas dos arremessos.")
    shots = frame.loc[pd.to_numeric(frame["is_field_goal"], errors="coerce").eq(1)].copy()
    shots["game_id"] = shots["game_id"].astype(str)
    games = schedule.drop_duplicates("game_id").copy()
    games["game_id"] = games["game_id"].astype(str)
    shots = shots.merge(
        games[["game_id", "game_date", "home_team_abbreviation", "away_team_abbreviation"]],
        on="game_id",
        how="inner",
    )
    shots["game_date"] = pd.to_datetime(shots["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    shots = shots.loc[shots["game_date"].notna() & shots["game_date"].le(utc_now().date().isoformat())].copy()
    shots["team"] = shots["team_tricode"].map(team_code)
    home, away = (
        shots["home_team_abbreviation"].map(team_code),
        shots["away_team_abbreviation"].map(team_code),
    )
    shots["opponent_code"] = away.where(shots["team"].eq(home), home)
    valid = shots["team"].eq(home) | shots["team"].eq(away)
    shots = (
        shots.loc[valid & shots["shot_value"].isin([2, 3])]
        .drop_duplicates(["game_id", "action_number"])
        .copy()
    )
    shots["x_ft"] = pd.to_numeric(shots["x_legacy"], errors="coerce") / 10
    shots["y_ft"] = pd.to_numeric(shots["y_legacy"], errors="coerce") / 10
    # Coordenadas ausentes não viram tentativas no aro.
    shots = shots.loc[np.isfinite(shots["x_ft"]) & np.isfinite(shots["y_ft"])].copy()
    shots["radial_ft"] = np.hypot(shots["x_ft"], shots["y_ft"])
    three = shots["shot_value"].eq(3)
    corner = three & shots["x_ft"].abs().ge(22) & shots["y_ft"].le(14)
    paint = shots["x_ft"].abs().le(8) & shots["y_ft"].between(-5.25, 13.75)
    shots["zone"] = np.select(
        [corner, three, shots["radial_ft"].lt(6), paint],
        ["Corner 3", "Above the break 3", "Aro (<6 pés)", "Garrafão (fora de <6 pés)"],
        default="Média distância",
    )
    shots["made"] = shots["shot_result"].eq("Made").astype(int)
    shots["season"] = season_label(year)
    shots["phase"] = shots["game_id"].map(game_phase)
    grouped = shots.groupby(
        ["season", "phase", "game_id", "game_date", "opponent_code", "zone"], as_index=False
    ).agg(attempts=("made", "size"), makes=("made", "sum"))
    grouped = grouped.rename(columns={"opponent_code": "team"})
    grouped["source"] = "NBA PBP / zonas geométricas"
    return grouped, shots


def _import_current_shots(db_path: str | Path, shots: pd.DataFrame) -> int:
    from .shot_storage import upsert_player_shots

    if shots.empty or str(shots["season"].iloc[0]) != current_season():
        return 0
    shots = shots.loc[shots["phase"].eq("Temporada regular") & shots["person_id"].gt(0)].copy()
    if shots.empty:
        return 0
    with sqlite3.connect(db_path) as db:
        names = dict(db.execute("SELECT player_id,player_name FROM player_game_stats ORDER BY game_date"))
        canonical = {
            (str(day)[:10], home, away): gid
            for gid, day, home, away in db.execute("SELECT game_id,game_date,home_team,away_team FROM games")
        }
    home = shots["home_team_abbreviation"].map(team_code).map(TEAM_ABBREVIATION_TO_NAME)
    away = shots["away_team_abbreviation"].map(team_code).map(TEAM_ABBREVIATION_TO_NAME)
    shots["game_id"] = [
        canonical.get((day, h, a), gid)
        for day, h, a, gid in zip(shots["game_date"], home, away, shots["game_id"], strict=True)
    ]
    shots["player_id"] = shots["person_id"].astype(int)
    shots["player_name"] = shots["player_id"].map(names).fillna(shots["player_name"])
    shots["game_event_id"] = shots["action_number"].astype(int)
    shots["team_name"] = shots["team"].map(TEAM_ABBREVIATION_TO_NAME)
    shots["opponent"] = shots["opponent_code"].map(TEAM_ABBREVIATION_TO_NAME)
    clock = shots["clock"].map(minutes).fillna(0)
    shots["minutes_remaining"] = np.floor(clock).astype(int)
    shots["seconds_remaining"] = np.round((clock % 1) * 60).astype(int).clip(0, 59)
    shots["event_type"] = np.where(shots["made"].eq(1), "Made Shot", "Missed Shot")
    shots["action_type"] = shots["sub_type"]
    shots["shot_type"] = np.where(shots["shot_value"].eq(3), "3PT Field Goal", "2PT Field Goal")
    shots["shot_zone_basic"] = shots["zone"].map(
        {
            "Corner 3": "Left Corner 3",
            "Above the break 3": "Above the Break 3",
            "Aro (<6 pés)": "In The Paint (Non-RA)",
            "Garrafão (fora de <6 pés)": "In The Paint (Non-RA)",
            "Média distância": "Mid-Range",
        }
    )
    shots.loc[shots["zone"].eq("Corner 3") & shots["x_ft"].gt(0), "shot_zone_basic"] = "Right Corner 3"
    shots.loc[shots["shot_value"].eq(2) & shots["radial_ft"].lt(4), "shot_zone_basic"] = "Restricted Area"
    shots["shot_zone_area"] = "Geometria PBP"
    shots["shot_zone_range"] = pd.cut(
        shots["radial_ft"],
        [-1, 8, 16, 24, np.inf],
        right=False,
        labels=["Less Than 8 ft.", "8-16 ft.", "16-24 ft.", "24+ ft."],
    ).astype(str)
    shots["loc_x"], shots["loc_y"] = shots["x_legacy"], shots["y_legacy"]
    shots["loc_x_ft"], shots["loc_y_ft"] = shots["x_ft"], shots["y_ft"]
    shots["shot_attempted"], shots["shot_made"] = 1, shots["made"]
    shots["source"] = "NBA PBP (geometria)"
    return upsert_player_shots(shots, Path(db_path))


def normalize_history(db_path: str | Path, *, years=None) -> dict:
    assets = read_assets(db_path)
    if years is not None and not assets.empty:
        assets = assets.loc[assets["year"].isin(years)]
    result: dict = {
        "team_boxes": 0,
        "team_seasons": 0,
        "defense_zones": 0,
        "new_current_shots": 0,
        "errors": [],
    }
    if assets.empty:
        return result
    root = history_root(db_path)
    for year in sorted(assets["year"].unique()):
        subset = assets.loc[assets["year"].eq(year)]

        def load(tag: str, prefix: str, subset=subset, **options):
            rows = subset.loc[subset["tag"].eq(tag) & subset["name"].str.startswith(prefix)]
            if rows.empty:
                return None, None
            asset = rows.iloc[0]
            return pd.read_parquet(root / asset["relative_path"], **options), asset

        try:
            schedule, _ = load("nba_stats_schedules", "nba_schedule_")
            index = {}
            if schedule is not None:
                for row in schedule.to_dict("records"):
                    index[
                        str(row["game_date"])[:10],
                        team_code(row["home_team_abbreviation"]),
                        team_code(row["away_team_abbreviation"]),
                    ] = str(row["game_id"])
            boxes, _ = load("espn_nba_team_boxscores", "team_box_")
            if boxes is not None:
                normalized = normalize_team_boxes(boxes, index, int(year))
                records = [tuple(row.values()) for row in json.loads(normalized.to_json(orient="records"))]
                with connect_history(db_path) as connection:
                    connection.executemany(
                        "INSERT OR REPLACE INTO team_boxes VALUES ("
                        + ",".join("?" for _ in normalized.columns)
                        + ")",
                        records,
                    )
                result["team_boxes"] += len(records)
            master, asset = load("nba_stats_leaguedash", "team_master_")
            if master is not None:
                records = []
                for row in json.loads(master.to_json(orient="records")):
                    team = team_code(row["team_name"])
                    if not team or row.get("gp", 0) <= 0 or row.get("per_mode") != "Totals":
                        continue
                    phase = "Playoffs" if row.get("season_type") == "Playoffs" else "Temporada regular"
                    records.append(
                        (
                            season_label(int(year)),
                            phase,
                            team,
                            json.dumps(row),
                            asset["source_url"],
                            asset["source_updated"],
                        )
                    )
                with connect_history(db_path) as connection:
                    connection.executemany(
                        "INSERT OR REPLACE INTO team_seasons VALUES (?,?,?,?,?,?)", records
                    )
                result["team_seasons"] += len(records)
            pbp, _ = load(
                "nba_stats_pbp",
                "nba_play_by_play_",
                columns=[
                    "game_id",
                    "action_number",
                    "is_field_goal",
                    "team_tricode",
                    "team_id",
                    "person_id",
                    "player_name",
                    "x_legacy",
                    "y_legacy",
                    "shot_result",
                    "shot_value",
                    "period",
                    "clock",
                    "sub_type",
                    "shot_distance",
                ],
                filters=[("is_field_goal", "==", 1)],
            )
            if pbp is not None and schedule is not None:
                zones, shots = normalize_pbp_zones(pbp, schedule, int(year))
                with connect_history(db_path) as connection:
                    ids = zones["game_id"].unique()
                    connection.executemany(
                        "DELETE FROM defense_zones WHERE game_id=?", [(gid,) for gid in ids]
                    )
                    connection.executemany(
                        "INSERT INTO defense_zones VALUES (?,?,?,?,?,?,?,?,?)",
                        zones.itertuples(index=False, name=None),
                    )
                result["defense_zones"] += len(zones)
                result["new_current_shots"] += _import_current_shots(db_path, shots)
        except Exception as error:
            result["errors"].append(
                {"year": int(year), "error": type(error).__name__, "detail": str(error)[:160]}
            )
    from .player_matchups import ingest_matchup_assets

    matchups = ingest_matchup_assets(db_path, years=years)
    result["matchups"] = matchups
    result["errors"].extend(matchups["errors"])
    return result
