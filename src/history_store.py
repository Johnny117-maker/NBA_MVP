"""Acervo público separado dos dados de treinamento e das previsões pessoais."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from .deploy_mode import read_only_active


def history_path(db_path: str | Path) -> Path:
    return Path(db_path).with_name("nba_history.sqlite")


def history_root(db_path: str | Path) -> Path:
    return Path(db_path).parent / "history"


def connect_history(db_path: str | Path) -> sqlite3.Connection:
    path = history_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    if not read_only_active():
        connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS assets (
            tag TEXT NOT NULL, name TEXT NOT NULL, year INTEGER NOT NULL,
            source_url TEXT NOT NULL, source_updated TEXT, fetched_at TEXT,
            sha256 TEXT, bytes INTEGER, rows INTEGER, columns INTEGER, relative_path TEXT,
            PRIMARY KEY(tag,name)
        );
        CREATE TABLE IF NOT EXISTS history_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS team_boxes (
            season TEXT, phase TEXT, game_id TEXT, game_date TEXT, team TEXT, opponent TEXT,
            is_home INTEGER, points REAL, opponent_points REAL, fgm REAL, fga REAL,
            fg3m REAL, fg3a REAL, ftm REAL, fta REAL, oreb REAL, dreb REAL,
            ast REAL, tov REAL, stl REAL, blk REAL, paint REAL, source TEXT,
            PRIMARY KEY(season,phase,game_id,team)
        );
        CREATE INDEX IF NOT EXISTS idx_history_boxes ON team_boxes(season,phase,team,game_date);
        CREATE TABLE IF NOT EXISTS team_seasons (
            season TEXT, phase TEXT, team TEXT, payload TEXT, source TEXT, updated_at TEXT,
            PRIMARY KEY(season,phase,team)
        );
        CREATE TABLE IF NOT EXISTS defense_zones (
            season TEXT, phase TEXT, game_id TEXT, game_date TEXT, team TEXT,
            zone TEXT, attempts INTEGER, makes INTEGER, source TEXT,
            PRIMARY KEY(season,phase,game_id,team,zone)
        );
        CREATE INDEX IF NOT EXISTS idx_history_zones ON defense_zones(season,phase,team,game_date);
        CREATE INDEX IF NOT EXISTS idx_history_zone_game ON defense_zones(game_id);
        CREATE TABLE IF NOT EXISTS defense_tracking (
            season TEXT, phase TEXT, team TEXT, category TEXT, games INTEGER,
            fgm REAL, fga REAL, as_of TEXT, fetched_at TEXT, source TEXT,
            PRIMARY KEY(season,phase,team,category)
        );
        CREATE TABLE IF NOT EXISTS player_matchups (
            game_id TEXT, game_date TEXT, season TEXT, phase TEXT,
            off_id INTEGER, off_name TEXT, off_team TEXT,
            def_id INTEGER, def_name TEXT, def_team TEXT, def_position TEXT,
            seconds REAL, possessions REAL, points REAL, fgm REAL, fga REAL,
            fg3m REAL, fg3a REAL, assists REAL, turnovers REAL, blocks REAL,
            switches REAL, shooting_fouls REAL, source TEXT,
            PRIMARY KEY(game_id,off_id,def_id)
        );
        CREATE INDEX IF NOT EXISTS idx_matchups_off ON player_matchups(off_id,season,phase,game_date);
        CREATE INDEX IF NOT EXISTS idx_matchups_def ON player_matchups(def_id,season,phase);
        CREATE INDEX IF NOT EXISTS idx_matchups_season ON player_matchups(season,phase,game_date);
        """
    )
    return connection


def read_assets(db_path: str | Path) -> pd.DataFrame:
    if not history_path(db_path).exists():
        return pd.DataFrame()
    with connect_history(db_path) as connection:
        return pd.read_sql_query("SELECT * FROM assets ORDER BY year DESC,tag,name", connection)


def get_history_state(db_path: str | Path, key: str, default=None):
    with connect_history(db_path) as connection:
        row = connection.execute("SELECT value FROM history_state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_history_state(db_path: str | Path, key: str, value) -> None:
    with connect_history(db_path) as connection:
        connection.execute("INSERT OR REPLACE INTO history_state VALUES (?,?)", (key, json.dumps(value)))
