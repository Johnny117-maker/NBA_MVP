"""Atribuições de marcação registradas pela NBA; não reconstrói posições por posse."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from nba_api.stats.static.teams import get_teams

from .history_normalize import game_phase, season_label
from .history_store import connect_history, history_root, read_assets
from .live_types import minutes, utc_now

MATCHUP_COLUMNS = [
    "game_id",
    "game_date",
    "season",
    "phase",
    "off_id",
    "off_name",
    "off_team",
    "def_id",
    "def_name",
    "def_team",
    "def_position",
    "seconds",
    "possessions",
    "points",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "assists",
    "turnovers",
    "blocks",
    "switches",
    "shooting_fouls",
    "source",
]
STATS = {
    "possessions": "partial_possessions",
    "points": "player_points",
    "fgm": "matchup_field_goals_made",
    "fga": "matchup_field_goals_attempted",
    "fg3m": "matchup_three_pointers_made",
    "fg3a": "matchup_three_pointers_attempted",
    "assists": "matchup_assists",
    "turnovers": "matchup_turnovers",
    "blocks": "matchup_blocks",
    "switches": "switches_on",
    "shooting_fouls": "shooting_fouls",
}


def normalize_matchups(
    frame: pd.DataFrame, schedule: pd.DataFrame, year: int, positions: dict | None = None
) -> pd.DataFrame:
    required = {
        "game_id",
        "off_person_id",
        "def_person_id",
        "off_first_name",
        "off_family_name",
        "def_first_name",
        "def_family_name",
        "off_team_id",
        "matchup_minutes",
        *STATS.values(),
    }
    if not required.issubset(frame):
        raise ValueError("Matchups sem identificadores ou estatísticas obrigatórias.")
    rows = frame.copy()
    rows["game_id"] = rows["game_id"].astype(str)
    context = (
        schedule[["game_id", "game_date", "home_team_id", "away_team_id"]].drop_duplicates("game_id").copy()
    )
    context["game_id"] = context["game_id"].astype(str)
    rows = rows.merge(context, on="game_id", how="inner", validate="many_to_one")
    if rows.empty:
        return pd.DataFrame(columns=MATCHUP_COLUMNS)
    rows["game_date"] = pd.to_datetime(rows["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    ids = {row["id"]: row["abbreviation"] for row in get_teams()}
    rows["off_team"] = rows["off_team_id"].map(ids)
    opponent = rows["away_team_id"].where(rows["off_team_id"].eq(rows["home_team_id"]), rows["home_team_id"])
    rows["def_team"] = opponent.map(ids)
    rows["off_id"] = pd.to_numeric(rows["off_person_id"], errors="coerce")
    rows["def_id"] = pd.to_numeric(rows["def_person_id"], errors="coerce")
    rows["off_name"] = (
        rows["off_first_name"].fillna("") + " " + rows["off_family_name"].fillna("")
    ).str.strip()
    rows["def_name"] = (
        rows["def_first_name"].fillna("") + " " + rows["def_family_name"].fillna("")
    ).str.strip()
    rows["def_position"] = rows["def_id"].map(positions or {}).fillna("Não informada")
    parsed = rows["matchup_minutes"].map(minutes) * 60
    rows["seconds"] = (
        pd.to_numeric(rows["matchup_minutes_sort"], errors="coerce").fillna(parsed)
        if "matchup_minutes_sort" in rows
        else parsed
    )
    for target, origin in STATS.items():
        rows[target] = pd.to_numeric(rows[origin], errors="coerce")
    numeric = ["seconds", *STATS]
    valid = rows[numeric].notna().all(axis=1) & np.isfinite(rows[numeric]).all(axis=1)
    valid &= rows[numeric].ge(0).all(axis=1) & rows["fgm"].le(rows["fga"]) & rows["fg3m"].le(rows["fg3a"])
    valid &= rows["fg3m"].le(rows["fgm"]) & rows["fg3a"].le(rows["fga"])
    valid &= rows["off_id"].gt(0) & rows["def_id"].gt(0) & rows["off_id"].ne(rows["def_id"])
    valid &= (
        rows["off_team"].notna()
        & rows["def_team"].notna()
        & rows["off_name"].ne("")
        & rows["def_name"].ne("")
    )
    valid &= rows["off_team_id"].eq(rows["home_team_id"]) | rows["off_team_id"].eq(rows["away_team_id"])
    if "def_team_id" in rows:
        valid &= pd.to_numeric(rows["def_team_id"], errors="coerce").eq(opponent)
    valid &= rows["game_date"].notna() & rows["game_date"].le(utc_now().date().isoformat())
    rows = rows.loc[valid].copy()
    rows["season"] = season_label(year)
    rows["phase"] = rows["game_id"].map(game_phase)
    rows["source"] = "NBA BoxScoreMatchupsV3 / SportsDataverse"
    return rows[MATCHUP_COLUMNS].drop_duplicates(["game_id", "off_id", "def_id"])


def ingest_matchup_assets(db_path: str | Path, *, years=None) -> dict:
    assets = read_assets(db_path)
    if years is not None and not assets.empty:
        assets = assets.loc[assets["year"].isin(years)]
    result: dict = {"rows": 0, "files": 0, "errors": []}
    if assets.empty:
        return result
    root = history_root(db_path)
    for asset in assets.loc[assets.tag.eq("nba_stats_game_matchups")].to_dict("records"):
        year = int(asset["year"])
        key = "matchups:" + asset["name"]
        with connect_history(db_path) as connection:
            previous = connection.execute("SELECT value FROM history_state WHERE key=?", (key,)).fetchone()
        if previous and json.loads(previous[0]) == asset["sha256"]:
            continue
        try:
            schedule_asset = assets.loc[assets.tag.eq("nba_stats_schedules") & assets.year.eq(year)].iloc[0]
            schedule = pd.read_parquet(root / schedule_asset["relative_path"])
            roster_asset = assets.loc[assets.tag.eq("nba_stats_rosters") & assets.year.eq(year)]
            positions = {}
            if not roster_asset.empty:
                roster = pd.read_parquet(root / roster_asset.iloc[0]["relative_path"])
                positions = dict(zip(roster["player_id"], roster["position"], strict=True))
            parquet = pq.ParquetFile(root / asset["relative_path"])
            with connect_history(db_path) as connection:
                for batch in parquet.iter_batches(batch_size=16000):
                    normalized = normalize_matchups(batch.to_pandas(), schedule, year, positions)
                    connection.executemany(
                        "INSERT OR REPLACE INTO player_matchups VALUES ("
                        + ",".join("?" for _ in MATCHUP_COLUMNS)
                        + ")",
                        normalized.itertuples(index=False, name=None),
                    )
                    result["rows"] += len(normalized)
                connection.execute(
                    "INSERT OR REPLACE INTO history_state VALUES (?,?)", (key, json.dumps(asset["sha256"]))
                )
            result["files"] += 1
        except Exception as error:
            result["errors"].append(
                {"file": asset["name"], "error": type(error).__name__, "detail": str(error)[:160]}
            )
    return result


def read_matchups(
    db_path: str | Path,
    season: str,
    phase: str,
    *,
    off_id: int | None = None,
    def_id: int | None = None,
    game_id: str | None = None,
) -> pd.DataFrame:
    where = ["season=?", "phase=?"]
    parameters: list[str | int] = [season, phase]
    if off_id is not None:
        where.append("off_id=?")
        parameters.append(off_id)
    if game_id is not None:
        where.append("game_id=?")
        parameters.append(game_id)
    if def_id is not None:
        where.append("def_id=?")
        parameters.append(def_id)
    with connect_history(db_path) as connection:
        return pd.read_sql_query(
            "SELECT * FROM player_matchups WHERE "
            + " AND ".join(where)
            + " ORDER BY game_date DESC,seconds DESC",
            connection,
            params=parameters,
        )


def attacker_summary(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    result = rows.groupby(["off_id", "off_name"], as_index=False).agg(
        off_team=("off_team", lambda teams: ", ".join(sorted(set(teams)))),
        games=("game_id", "nunique"),
        seconds=("seconds", "sum"),
        possessions=("possessions", "sum"),
        points=("points", "sum"),
        fgm=("fgm", "sum"),
        fga=("fga", "sum"),
        fg3m=("fg3m", "sum"),
        fg3a=("fg3a", "sum"),
        turnovers=("turnovers", "sum"),
    )
    result["fg_pct"] = result.fgm / result.fga.replace(0, np.nan)
    result["fg3_pct"] = result.fg3m / result.fg3a.replace(0, np.nan)
    result["efg_pct"] = (result.fgm + 0.5 * result.fg3m) / result.fga.replace(0, np.nan)
    result["pts_100_partial"] = 100 * result.points / result.possessions.replace(0, np.nan)
    return result.sort_values("fga", ascending=False).reset_index(drop=True)


def defender_opponents(db_path: str | Path, season: str, phase: str, defender_id: int):
    rows = read_matchups(db_path, season, phase, def_id=defender_id)
    summary = attacker_summary(rows)
    if summary.empty:
        return rows, summary
    with connect_history(db_path) as connection:
        reference = pd.read_sql_query(
            "SELECT off_id,SUM(fgm) other_fgm,SUM(fga) other_fga FROM player_matchups "
            "WHERE season=? AND phase=? AND def_id<>? AND off_id IN "
            "(SELECT DISTINCT off_id FROM player_matchups WHERE season=? AND phase=? AND def_id=?) "
            "GROUP BY off_id",
            connection,
            params=(season, phase, defender_id, season, phase, defender_id),
        )
    summary = summary.merge(reference, on="off_id", how="left")
    summary["reference_pct"] = summary.other_fgm / summary.other_fga.where(summary.other_fga.ge(20))
    summary["difference_pp"] = 100 * (summary.fg_pct - summary.reference_pct).where(summary.fga.ge(5))
    return rows, summary


def defender_summary(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    result = rows.groupby(["def_id", "def_name", "def_position"], as_index=False).agg(
        games=("game_id", "nunique"),
        seconds=("seconds", "sum"),
        possessions=("possessions", "sum"),
        points=("points", "sum"),
        fgm=("fgm", "sum"),
        fga=("fga", "sum"),
        fg3m=("fg3m", "sum"),
        fg3a=("fg3a", "sum"),
        switches=("switches", "sum"),
        turnovers=("turnovers", "sum"),
    )
    result["minutes"] = result["seconds"] / 60
    result["fg_pct"] = result["fgm"] / result["fga"].replace(0, np.nan)
    result["fg3_pct"] = result["fg3m"] / result["fg3a"].replace(0, np.nan)
    result["pts_100_partial"] = 100 * result["points"] / result["possessions"].replace(0, np.nan)
    return result.sort_values("seconds", ascending=False).reset_index(drop=True)


def collect_game_matchups(db_path: str | Path, game_id: str) -> int:
    from nba_api.stats.endpoints.boxscorematchupsv3 import BoxScoreMatchupsV3

    if not re.fullmatch(r"\d{10}", game_id):
        raise ValueError("A consulta exige um identificador NBA oficial de dez dígitos.")
    assets = read_assets(db_path)
    schedule = None
    year = 0
    for asset in (
        assets.loc[assets.tag.eq("nba_stats_schedules")]
        .sort_values("year", ascending=False)
        .to_dict("records")
    ):
        candidate = pd.read_parquet(history_root(db_path) / asset["relative_path"])
        if candidate["game_id"].astype(str).eq(game_id).any():
            schedule, year = candidate, int(asset["year"])
            break
    if schedule is None:
        raise ValueError("Atualize o calendário NBA do acervo antes de consultar esta partida.")
    context = schedule.loc[schedule["game_id"].astype(str).eq(game_id)].iloc[0]
    if (
        str(context["game_date"])[:10] > utc_now().date().isoformat()
        or context["home_wl"] not in {"W", "L"}
        or not (float(context["home_pts"] or 0) > 0 and float(context["away_pts"] or 0) > 0)
    ):
        raise ValueError("A partida ainda não possui placar final disponível no acervo.")
    frame = BoxScoreMatchupsV3(game_id, timeout=8).get_data_frames()[0]
    rename = {
        "gameId": "game_id",
        "teamId": "off_team_id",
        "personIdOff": "off_person_id",
        "personIdDef": "def_person_id",
        "firstNameOff": "off_first_name",
        "familyNameOff": "off_family_name",
        "firstNameDef": "def_first_name",
        "familyNameDef": "def_family_name",
        "matchupMinutes": "matchup_minutes",
        "matchupMinutesSort": "matchup_minutes_sort",
        "partialPossessions": "partial_possessions",
        "playerPoints": "player_points",
        "matchupFieldGoalsMade": "matchup_field_goals_made",
        "matchupFieldGoalsAttempted": "matchup_field_goals_attempted",
        "matchupThreePointersMade": "matchup_three_pointers_made",
        "matchupThreePointersAttempted": "matchup_three_pointers_attempted",
        "matchupAssists": "matchup_assists",
        "matchupTurnovers": "matchup_turnovers",
        "matchupBlocks": "matchup_blocks",
        "switchesOn": "switches_on",
        "shootingFouls": "shooting_fouls",
    }
    normalized = normalize_matchups(frame.rename(columns=rename), schedule, year)
    normalized["source"] = "NBA BoxScoreMatchupsV3 / consulta direta"
    with connect_history(db_path) as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO player_matchups VALUES (" + ",".join("?" for _ in MATCHUP_COLUMNS) + ")",
            normalized.itertuples(index=False, name=None),
        )
    return len(normalized)


def collect_pending_matchups(db_path: str | Path, *, limit: int = 8) -> dict:
    """Retoma partidas da temporada atual; a primeira recusa da fonte interrompe o lote."""
    from .live_types import current_season

    year = int(current_season()[:4]) + 1
    assets = read_assets(db_path)
    match = assets.loc[assets.tag.eq("nba_stats_schedules") & assets.year.eq(year)]
    result: dict = {"collected": 0, "rows": 0, "error": None}
    if match.empty:
        return result
    schedule = pd.read_parquet(history_root(db_path) / match.iloc[0].relative_path)
    done = schedule.loc[
        schedule.home_wl.isin(["W", "L"])
        & schedule.game_id.astype(str).str.startswith(("002", "004", "005"))
        & schedule.game_date.astype(str).str[:10].le(utc_now().date().isoformat())
    ]
    with connect_history(db_path) as connection:
        known = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT game_id FROM player_matchups WHERE season=?", (current_season(),)
            )
        }
    pending = [str(gid) for gid in done.game_id if str(gid) not in known][:limit]
    for game_id in pending:
        try:
            count = collect_game_matchups(db_path, game_id)
            if not count:
                result["error"] = "A fonte ainda não publicou as marcações desta partida."
                break
            result["collected"] += 1
            result["rows"] += count
        except Exception as error:
            result["error"] = type(error).__name__
            break
    return result
