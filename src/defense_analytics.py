"""Índice defensivo descritivo e arremessos adversários da mesma amostra de jogos."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .history_normalize import normalize_pbp_zones
from .history_store import connect_history, history_root, read_assets

DEFENSE_WEIGHTS = {"drtg": 40.0, "paint_allowed_100": 20.0, "opp_3p_pct": 20.0, "dreb_pct": 20.0}
DEFENSE_LABELS = {
    "drtg": "Eficiência geral",
    "paint_allowed_100": "Garrafão",
    "opp_3p_pct": "Aproveitamento de três cedido",
    "dreb_pct": "Rebote defensivo",
}


def defense_index(summary: pd.DataFrame, weights: dict | None = None, min_games: int = 5) -> pd.DataFrame:
    weights = DEFENSE_WEIGHTS if weights is None else weights
    if any(
        key not in DEFENSE_WEIGHTS or not np.isfinite(value) or value < 0 for key, value in weights.items()
    ):
        raise ValueError("Pesos defensivos inválidos.")
    active = {key: value for key, value in weights.items() if value > 0}
    if not active or min_games < 1:
        raise ValueError("Selecione ao menos um peso positivo e uma amostra mínima.")
    result = summary.copy()
    result["defense_index"] = np.nan
    for metric in active:
        result[metric + "_strength"] = np.nan
    if result.empty:
        return result
    eligible = result.games.ge(min_games) & result[list(active)].notna().all(axis=1)
    if "paint_allowed_100" in active:
        eligible &= result.paint_games.eq(result.games)
    cohort = result.loc[eligible]
    if len(cohort) < 2:
        return result
    scores = []
    for metric, weight in active.items():
        # Empates recebem percentil médio; uma liga empatada fica em 50.
        rank = cohort[metric].rank(method="average", ascending=metric == "dreb_pct")
        strength = 100 * (rank - 1) / (len(cohort) - 1)
        result.loc[eligible, metric + "_strength"] = strength
        scores.append(strength * weight / sum(active.values()))
    result.loc[eligible, "defense_index"] = sum(scores)
    return result


def defense_shots(db_path: str | Path, season: str, phase: str, team: str, last_n: int = 0) -> pd.DataFrame:
    if last_n < 0:
        raise ValueError("Amostra inválida.")
    with connect_history(db_path) as connection:
        games = pd.read_sql_query(
            "SELECT b.game_id,b.game_date,b.opponent,o.fga FROM team_boxes b "
            "JOIN team_boxes o ON b.game_id=o.game_id AND b.opponent=o.team "
            "AND b.season=o.season AND b.phase=o.phase "
            "WHERE b.season=? AND b.phase=? AND b.team=? ORDER BY b.game_date DESC,b.game_id DESC",
            connection,
            params=(season, phase, team),
        )
    if games.empty:
        return pd.DataFrame()
    if last_n:
        games = games.head(last_n)
    assets = read_assets(db_path)
    if assets.empty:
        return pd.DataFrame()
    year = int(season[:4]) + 1
    selected = assets.loc[assets.year.eq(year)]
    pbp = selected.loc[selected.tag.eq("nba_stats_pbp")]
    schedule = selected.loc[selected.tag.eq("nba_stats_schedules")]
    if pbp.empty or schedule.empty:
        return pd.DataFrame()
    columns = [
        "game_id",
        "action_number",
        "is_field_goal",
        "team_tricode",
        "person_id",
        "x_legacy",
        "y_legacy",
        "shot_result",
        "shot_value",
    ]
    root = history_root(db_path)
    raw = pd.read_parquet(
        root / pbp.iloc[0].relative_path,
        columns=columns,
        filters=[("is_field_goal", "==", 1), ("game_id", "in", games.game_id.tolist())],
    )
    calendar = pd.read_parquet(root / schedule.iloc[0].relative_path)
    _, shots = normalize_pbp_zones(raw, calendar, year)
    shots = shots.loc[shots.opponent_code.eq(team) & shots.phase.eq(phase)].copy()
    # A mesma regra do painel regional: todas as FGA adversárias precisam estar localizadas.
    counts = shots.groupby("game_id").size()
    complete = games.loc[games.game_id.map(counts).eq(games.fga), "game_id"]
    return shots.loc[shots.game_id.isin(complete)].reset_index(drop=True)


def court_cells(shots: pd.DataFrame, bin_size: float = 3.0) -> pd.DataFrame:
    if not 1 <= bin_size <= 10:
        raise ValueError("O tamanho da célula deve ficar entre 1 e 10 pés.")
    if shots.empty:
        return pd.DataFrame()
    valid = shots.loc[
        np.isfinite(shots.x_ft)
        & np.isfinite(shots.y_ft)
        & shots.x_ft.between(-25, 25)
        & shots.y_ft.between(-5.25, 42)
    ].copy()
    valid["x_bin"] = np.floor((valid.x_ft + 25) / bin_size)
    valid["y_bin"] = np.floor((valid.y_ft + 5.25) / bin_size)
    cells = valid.groupby(["x_bin", "y_bin"], as_index=False).agg(
        attempts=("made", "size"), makes=("made", "sum")
    )
    cells["x"] = -25 + (cells.x_bin + 0.5) * bin_size
    cells["y"] = -5.25 + (cells.y_bin + 0.5) * bin_size
    cells["fg_pct"] = cells.makes / cells.attempts
    return cells


def defense_evolution(db_path: str | Path, season: str, phase: str, team: str) -> pd.DataFrame:
    with connect_history(db_path) as connection:
        rows = pd.read_sql_query(
            "SELECT b.game_date,b.game_id,b.opponent,b.fga,b.fta,b.oreb,b.tov,"
            "o.fga opp_fga,o.fta opp_fta,o.oreb opp_oreb,o.tov opp_tov,o.points opp_points "
            "FROM team_boxes b JOIN team_boxes o ON b.game_id=o.game_id AND b.opponent=o.team "
            "AND b.season=o.season AND b.phase=o.phase WHERE b.season=? AND b.phase=? AND b.team=? "
            "ORDER BY b.game_date,b.game_id",
            connection,
            params=(season, phase, team),
        )
    if rows.empty:
        return rows
    rows["possessions"] = 0.5 * (
        (rows.fga + 0.44 * rows.fta - rows.oreb + rows.tov)
        + (rows.opp_fga + 0.44 * rows.opp_fta - rows.opp_oreb + rows.opp_tov)
    )
    rows["drtg_10"] = (
        100
        * rows.opp_points.rolling(10, min_periods=5).sum()
        / rows.possessions.rolling(10, min_periods=5).sum().replace(0, np.nan)
    )
    return rows
