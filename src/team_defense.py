"""Defesa por equipe: taxas ponderadas, denominadores e procedência explícitos."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .history_store import connect_history, history_path, history_root, read_assets
from .live_providers import team_code
from .live_types import utc_now
from .nba_teams import TEAM_ABBREVIATION_TO_NAME

REGULAR = "Temporada regular"
ZONES = ("Aro (<6 pés)", "Garrafão (fora de <6 pés)", "Média distância", "Corner 3", "Above the break 3")


def _local_boxes(db_path: str | Path, season: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as connection:
        frame = pd.read_sql_query(
            "SELECT game_id,date(game_date) game_date,team,opponent,MAX(is_home) is_home,"
            "SUM(pts) points,SUM(fgm) fgm,SUM(fga) fga,SUM(fg3m) fg3m,SUM(fg3a) fg3a,"
            "SUM(ftm) ftm,SUM(fta) fta,SUM(oreb) oreb,SUM(dreb) dreb,SUM(ast) ast,"
            "SUM(tov) tov,SUM(stl) stl,SUM(blk) blk FROM player_game_stats WHERE season=? "
            "GROUP BY game_id,date(game_date),team,opponent",
            connection,
            params=(season,),
        )
    frame["paint"] = np.nan
    frame["source"] = "Soma dos boxscores locais"
    return frame


def _ratio(numerator, denominator):
    return numerator / denominator if denominator and pd.notna(denominator) and denominator > 0 else np.nan


def defense_tables(
    db_path: str | Path, season: str, phase: str = REGULAR, last_n: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if last_n < 0:
        raise ValueError("A janela de jogos não pode ser negativa.")
    with connect_history(db_path) as connection:
        boxes = pd.read_sql_query(
            "SELECT * FROM team_boxes WHERE season=? AND phase=?", connection, params=(season, phase)
        )
        masters = pd.read_sql_query(
            "SELECT * FROM team_seasons WHERE season=? AND phase=?", connection, params=(season, phase)
        )
        zones = pd.read_sql_query(
            "SELECT * FROM defense_zones WHERE season=? AND phase=?", connection, params=(season, phase)
        )
        tracking = pd.read_sql_query(
            "SELECT * FROM defense_tracking WHERE season=? AND phase=?", connection, params=(season, phase)
        )
    if boxes.empty and phase == REGULAR:
        boxes = _local_boxes(db_path, season)
    if boxes.empty:
        return pd.DataFrame(), pd.DataFrame()
    numeric = ["points", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "tov"]
    boxes = boxes.loc[boxes[numeric].notna().all(axis=1)].copy()
    if boxes.empty:
        return pd.DataFrame(), pd.DataFrame()
    # O denominador é composto pelo mesmo conjunto de partidas nos dois lados.
    games = boxes.merge(
        boxes,
        left_on=["game_id", "opponent"],
        right_on=["game_id", "team"],
        suffixes=("", "_opp"),
        validate="one_to_one",
    )
    games = games.loc[games["opponent_opp"].eq(games["team"])].sort_values(["game_date", "game_id"])
    if last_n:
        games = games.groupby("team", group_keys=False).tail(last_n)
    games["poss_est"] = 0.5 * (
        (games["fga"] + 0.44 * games["fta"] - games["oreb"] + games["tov"])
        + (games["fga_opp"] + 0.44 * games["fta_opp"] - games["oreb_opp"] + games["tov_opp"])
    )
    # Só usa regiões de partidas cujo PBP cobre todas as tentativas adversárias.
    zone_rows = pd.DataFrame()
    if not zones.empty:
        totals = zones.groupby(["game_id", "team"], as_index=False)["attempts"].sum()
        coverage = totals.merge(games[["game_id", "team", "fga_opp"]], on=["game_id", "team"])
        complete = coverage.loc[coverage["attempts"].eq(coverage["fga_opp"]), ["game_id", "team"]]
        zone_rows = zones.merge(complete, on=["game_id", "team"])
    official = {row["team"]: json.loads(row["payload"]) for row in masters.to_dict("records")}
    master_dates = dict(zip(masters.get("team", []), masters.get("updated_at", []), strict=True))
    result, region_rows = [], []
    for team, team_games in games.groupby("team"):
        n = len(team_games)
        shots = zone_rows.loc[zone_rows["team"].eq(team)] if not zone_rows.empty else pd.DataFrame()
        source = official.get(team, {}) if last_n == 0 else {}
        matching = (
            source.get("gp") == n and str(master_dates.get(team, ""))[:10] >= team_games["game_date"].max()
        )
        drtg = source.get("adv_def_rating", source.get("def_def_rating")) if matching else None
        paint_total = source.get("misc_opp_pts_paint", source.get("def_opp_pts_paint")) if matching else None
        paint_count = int(team_games["paint_opp"].notna().sum())
        fg3a, fg3m = team_games["fg3a_opp"].sum(), team_games["fg3m_opp"].sum()
        rim = shots.loc[shots["zone"].eq("Aro (<6 pés)")] if not shots.empty else pd.DataFrame()
        region_games = int(shots["game_id"].nunique()) if not shots.empty else 0
        row = {
            "team": team,
            "team_name": TEAM_ABBREVIATION_TO_NAME.get(team, team),
            "games": n,
            "latest_game": str(team_games["game_date"].max()),
            "drtg": float(drtg)
            if drtg is not None
            else 100 * _ratio(team_games["points_opp"].sum(), team_games["poss_est"].sum()),
            "drtg_method": "NBA Stats oficial" if drtg is not None else "Estimado por posses de boxscore",
            "points_allowed": team_games["points_opp"].mean(),
            "opp_3pa": fg3a / n,
            "opp_3p_pct": _ratio(fg3m, fg3a),
            "opp_3pa_100": 100 * _ratio(fg3a, team_games["poss_est"].sum()),
            "opp_3pa_share": _ratio(fg3a, team_games["fga_opp"].sum()),
            "paint_allowed": float(paint_total) / n
            if paint_total is not None
            else (team_games["paint_opp"].mean() if paint_count else np.nan),
            "paint_games": n if paint_total is not None else paint_count,
            "paint_method": "NBA Stats oficial" if paint_total is not None else "Boxscore ESPN",
            "rim_fg_pct": _ratio(rim["makes"].sum(), rim["attempts"].sum()) if not rim.empty else np.nan,
            "rim_attempts": int(rim["attempts"].sum()) if not rim.empty else 0,
            "zone_games": region_games,
            "dreb_pct": _ratio(
                team_games["dreb"].sum(), team_games["dreb"].sum() + team_games["oreb_opp"].sum()
            ),
            "tov_forced": team_games["tov_opp"].mean(),
            "blocks": team_games["blk"].mean(),
            "tracking_dfg_pct": np.nan,
            "tracking_fga": 0,
        }
        if not tracking.empty and not last_n:
            tracked = tracking.loc[tracking["team"].eq(team) & tracking["category"].eq("Less Than 6Ft")]
            if (
                not tracked.empty
                and str(tracked.iloc[0]["as_of"]) >= row["latest_game"]
                and int(tracked.iloc[0]["games"]) == n
            ):
                observed = tracked.iloc[0]
                row["tracking_dfg_pct"] = _ratio(observed["fgm"], observed["fga"])
                row["tracking_fga"] = observed["fga"]
        result.append(row)
        for zone in ZONES:
            observed = shots.loc[shots["zone"].eq(zone)] if not shots.empty else pd.DataFrame()
            attempts = int(observed["attempts"].sum()) if not observed.empty else 0
            makes = int(observed["makes"].sum()) if not observed.empty else 0
            region_rows.append(
                {
                    "team": team,
                    "zone": zone,
                    "attempts": attempts,
                    "makes": makes,
                    "games": region_games,
                    "attempts_game": _ratio(attempts, region_games),
                    "fg_pct": _ratio(makes, attempts),
                    "frequency": _ratio(attempts, shots["attempts"].sum()) if not shots.empty else np.nan,
                }
            )
    summary = pd.DataFrame(result)
    if not summary.empty:
        for metric in ("drtg", "paint_allowed", "opp_3pa", "opp_3p_pct", "rim_fg_pct"):
            summary[metric + "_rank"] = summary[metric].rank(method="min", ascending=True).astype("Int64")
    return summary, pd.DataFrame(region_rows)


def collect_team_tracking(db_path: str | Path, season: str, through: date) -> int:
    from nba_api.stats.endpoints.leaguedashptteamdefend import LeagueDashPtTeamDefend

    start = int(season[:4])
    if season != f"{start}-{(start + 1) % 100:02d}" or through > utc_now().date():
        raise ValueError("Temporada ou data de corte inválida.")
    frame = LeagueDashPtTeamDefend(
        season=season,
        defense_category="Less Than 6Ft",
        per_mode_simple="Totals",
        date_to_nullable=through.strftime("%m/%d/%Y"),
        timeout=8,
    ).get_data_frames()[0]
    required = {"TEAM_ABBREVIATION", "D_FGM", "D_FGA", "GP"}
    if not required.issubset(frame):
        raise ValueError("O formato do tracking mudou; nenhum valor foi importado.")
    records = []
    for row in frame.to_dict("records"):
        team = team_code(row["TEAM_ABBREVIATION"])
        made, attempts = float(row["D_FGM"]), float(row["D_FGA"])
        if not team or not np.isfinite([made, attempts]).all() or not 0 <= made <= attempts:
            raise ValueError("Tracking com equipe ou contagens inválidas.")
        records.append(
            (
                season,
                REGULAR,
                team,
                "Less Than 6Ft",
                int(row["GP"]),
                made,
                attempts,
                through.isoformat(),
                utc_now().isoformat(),
                "https://www.nba.com/stats/teams/defense-dash-lt6",
            )
        )
    with connect_history(db_path) as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO defense_tracking VALUES (?,?,?,?,?,?,?,?,?,?)", records
        )
    return len(records)


def defense_fingerprint(db_path: str | Path) -> tuple:
    return tuple(
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in (Path(db_path), history_path(db_path), Path(str(history_path(db_path)) + "-wal"))
        if path.exists()
    )


def rim_defenders(db_path: str | Path, season: str, team: str) -> pd.DataFrame:
    assets = read_assets(db_path)
    if assets.empty:
        return pd.DataFrame()
    year = int(season[:4]) + 1
    match = assets.loc[
        assets["tag"].eq("nba_stats_leaguedash")
        & assets["name"].eq(f"player_tracking_defense_{year}.parquet")
    ]
    if match.empty:
        return pd.DataFrame()
    frame = pd.read_parquet(history_root(db_path) / match.iloc[0]["relative_path"])
    required = {"team_abbreviation", "player_name", "gp", "def_rim_fgm", "def_rim_fga"}
    if not required.issubset(frame):
        return pd.DataFrame()
    frame = frame.loc[frame["team_abbreviation"].map(team_code).eq(team)].copy()
    frame["rim_pct"] = frame["def_rim_fgm"] / frame["def_rim_fga"].replace(0, np.nan)
    return frame[["player_name", "gp", "def_rim_fgm", "def_rim_fga", "rim_pct"]]
