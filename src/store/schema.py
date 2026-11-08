"""Esquema do SQLite, migrações e criação do banco."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..app_paths import data_path

DEFAULT_DB_PATH = data_path("nba.db")


_GAMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    game_date TEXT NOT NULL,
    season TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_points INTEGER NOT NULL,
    away_points INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_matchup_day ON games(date(game_date),home_team,away_team);
CREATE TABLE IF NOT EXISTS game_id_aliases (alias TEXT PRIMARY KEY, canonical_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS player_id_aliases (alias INTEGER PRIMARY KEY, canonical_id INTEGER NOT NULL);
"""

_PLAYER_GAME_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_game_stats (
    game_id TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    season TEXT NOT NULL,
    player_name TEXT NOT NULL,
    team TEXT NOT NULL,
    opponent TEXT NOT NULL,
    is_home INTEGER NOT NULL,
    minutes REAL NOT NULL,
    pts INTEGER NOT NULL,
    oreb INTEGER NOT NULL,
    dreb INTEGER NOT NULL,
    reb INTEGER NOT NULL,
    ast INTEGER NOT NULL,
    stl INTEGER NOT NULL,
    blk INTEGER NOT NULL,
    tov INTEGER NOT NULL,
    pf INTEGER NOT NULL,
    fgm INTEGER NOT NULL,
    fga INTEGER NOT NULL,
    fg3m INTEGER NOT NULL,
    fg3a INTEGER NOT NULL,
    ftm INTEGER NOT NULL,
    fta INTEGER NOT NULL,
    is_starter INTEGER,
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_player_games_player_id ON player_game_stats(player_id);
"""

_TEAM_ADVANCED_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_advanced_stats (
    game_id TEXT NOT NULL,
    team TEXT NOT NULL,
    off_rating REAL NOT NULL,
    def_rating REAL NOT NULL,
    net_rating REAL NOT NULL,
    pace REAL NOT NULL,
    PRIMARY KEY (game_id, team)
);
"""

_TEAM_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_win_probability REAL NOT NULL,
    predicted_home_score REAL NOT NULL,
    predicted_away_score REAL NOT NULL,
    confidence TEXT NOT NULL,
    actual_home_score INTEGER,
    actual_away_score INTEGER,
    resolved_at TEXT
);
"""

_PLAYER_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    opponent TEXT,
    is_home INTEGER NOT NULL,
    target_game_date TEXT,
    predicted_minutes REAL NOT NULL,
    predicted_pts REAL NOT NULL,
    predicted_reb REAL NOT NULL,
    predicted_ast REAL NOT NULL,
    confidence TEXT NOT NULL,
    actual_game_date TEXT,
    actual_opponent TEXT,
    actual_is_home INTEGER,
    actual_minutes REAL,
    actual_pts REAL,
    actual_reb REAL,
    actual_ast REAL,
    resolved_at TEXT
);
"""

_MODEL_TRAINING_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_training_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trained_at TEXT NOT NULL,
    model_type TEXT NOT NULL,
    n_games INTEGER NOT NULL,
    metrics TEXT NOT NULL
);
"""

_GAME_COLUMNS = [
    "game_id",
    "game_date",
    "season",
    "home_team",
    "away_team",
    "home_points",
    "away_points",
]

_TEAM_ADVANCED_COLUMNS = ["game_id", "team", "off_rating", "def_rating", "net_rating", "pace"]

_PLAYER_GAME_COLUMNS = [
    "game_id",
    "player_id",
    "game_date",
    "season",
    "player_name",
    "team",
    "opponent",
    "is_home",
    "minutes",
    "pts",
    "oreb",
    "dreb",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
]


def _migrate_player_game_stats(connection: sqlite3.Connection) -> None:
    """Adiciona colunas novas a um `player_game_stats` já existente.

    `CREATE TABLE IF NOT EXISTS` não altera uma tabela que já existe — bancos
    coletados antes da coluna `is_starter` existir (Fase 5 da titularidade)
    precisam desse `ALTER TABLE` para ganhá-la sem perder os dados já
    coletados.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(player_game_stats)")}
    if "is_starter" not in columns:
        connection.execute("ALTER TABLE player_game_stats ADD COLUMN is_starter INTEGER")


def _migrate_player_predictions(connection: sqlite3.Connection) -> None:
    """Adiciona campos de data/alvo e contexto real sem descartar previsões antigas."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(player_predictions)")}
    migrations = {
        "target_game_date": "TEXT",
        "actual_game_date": "TEXT",
        "actual_opponent": "TEXT",
        "actual_is_home": "INTEGER",
    }
    for column, sql_type in migrations.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE player_predictions ADD COLUMN {column} {sql_type}"
            )


def init_db(path: Path = DEFAULT_DB_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            _GAMES_SCHEMA
            + _PLAYER_GAME_STATS_SCHEMA
            + _TEAM_ADVANCED_STATS_SCHEMA
            + _TEAM_PREDICTIONS_SCHEMA
            + _PLAYER_PREDICTIONS_SCHEMA
            + _MODEL_TRAINING_LOG_SCHEMA
        )
        _migrate_player_game_stats(connection)
        _migrate_player_predictions(connection)
