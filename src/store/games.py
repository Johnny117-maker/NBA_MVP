"""Jogos, estatísticas de jogadores e de times: gravação e leitura."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ..entity_ids import reconcile_official_player
from .schema import _GAME_COLUMNS, _PLAYER_GAME_COLUMNS, _TEAM_ADVANCED_COLUMNS, DEFAULT_DB_PATH, init_db


def read_dashboard_leaders(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Líderes da temporada mais recente; mínimo adaptado ao início da temporada, até 10 jogos.

    Agrega no SQLite para a abertura do painel não carregar todos os boxscores.
    A equipe é a última registrada nessa temporada, incluindo jogadores trocados.
    """
    if not Path(path).exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_game_stats'"
        ).fetchone()
        if not exists:
            return pd.DataFrame()
        return pd.read_sql_query(
            """
            WITH recent AS (
                SELECT * FROM player_game_stats
                WHERE season = (SELECT season FROM player_game_stats ORDER BY game_date DESC LIMIT 1)
            ), counts AS (
                SELECT COUNT(*) AS n FROM recent GROUP BY player_id
            ), qualification AS (
                SELECT MIN(10, MAX(n)) AS minimum_games FROM counts
            ), leaders AS (
                SELECT player_id, season, COUNT(*) AS games, AVG(pts) AS pts,
                       AVG(reb) AS reb, AVG(ast) AS ast
                FROM recent GROUP BY player_id, season
                HAVING COUNT(*) >= (SELECT minimum_games FROM qualification)
                ORDER BY pts DESC, player_id LIMIT 4
            )
            SELECT l.*, r.player_name, r.team, (SELECT minimum_games FROM qualification) AS minimum_games
            FROM leaders l
            JOIN player_game_stats r ON r.rowid = (
                SELECT rowid FROM player_game_stats p WHERE p.player_id = l.player_id
                AND p.season = l.season ORDER BY p.game_date DESC, p.game_id DESC LIMIT 1
            ) ORDER BY l.pts DESC, l.player_id
            """, connection,
        )


def upsert_games(games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere jogos novos, ignorando os que já existem (mesmo game_id). Retorna quantos entraram."""
    init_db(path)
    rows = games.copy()
    rows["game_date"] = rows["game_date"].astype(str)

    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        for index, row in rows.iterrows():
            original = str(row["game_id"])
            existing = connection.execute(
                "SELECT game_id FROM games WHERE date(game_date)=? AND home_team=? AND away_team=? LIMIT 1",
                (pd.Timestamp(row["game_date"]).date().isoformat(), row["home_team"], row["away_team"]),
            ).fetchone()
            if existing and existing[0] != original:
                rows.at[index, "game_id"] = existing[0]
                connection.execute(
                    "INSERT OR REPLACE INTO game_id_aliases VALUES (?,?)", (original, existing[0])
                )
        connection.executemany(
            """
            INSERT OR IGNORE INTO games
                (game_id, game_date, season, home_team, away_team, home_points, away_points)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows[_GAME_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    return after - before


def apply_game_aliases(rows: pd.DataFrame, connection: sqlite3.Connection) -> pd.DataFrame:
    """Mantém o mesmo confronto ao combinar logs NBA, ESPN, arremessos e ratings."""
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='game_id_aliases'").fetchone()
    if not exists or rows.empty:
        return rows
    aliases = dict(connection.execute("SELECT alias,canonical_id FROM game_id_aliases").fetchall())
    if not aliases:
        return rows
    result = rows.copy()
    result["game_id"] = result["game_id"].astype(str).map(lambda value: aliases.get(value, value))
    return result


def read_raw_games(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Banco de dados não encontrado em {path}. "
            "Rode 'python scripts/update_data.py' para coletar os jogos."
        )
    with sqlite3.connect(path) as connection:
        data = pd.read_sql_query("SELECT * FROM games ORDER BY game_date", connection)
    if data.empty:
        raise ValueError("O banco de dados não tem nenhum jogo ainda.")
    data["game_date"] = pd.to_datetime(data["game_date"])
    return data


def count_games(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]


def list_seasons(path: Path = DEFAULT_DB_PATH) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT DISTINCT season FROM games ORDER BY season"
        ).fetchall()
    return [row[0] for row in rows]


def upsert_player_games(player_games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere estatísticas de jogadores novas, ignorando duplicatas (game_id, player_id)."""
    init_db(path)
    rows = player_games.copy()
    rows["game_date"] = rows["game_date"].astype(str)
    rows["is_home"] = rows["is_home"].astype(int)

    with sqlite3.connect(path) as connection:
        rows = apply_game_aliases(rows, connection)
        for player_id, name in rows[["player_id", "player_name"]].drop_duplicates().itertuples(index=False):
            reconcile_official_player(connection, int(player_id), str(name))
        before = connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO player_game_stats
                ({", ".join(_PLAYER_GAME_COLUMNS)})
            VALUES ({", ".join("?" for _ in _PLAYER_GAME_COLUMNS)})
            """,
            rows[_PLAYER_GAME_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]
    return after - before


def read_player_games(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Banco de dados não encontrado em {path}. "
            "Rode 'python scripts/update_data.py' para coletar os jogadores."
        )
    with sqlite3.connect(path) as connection:
        data = pd.read_sql_query(
            "SELECT * FROM player_game_stats ORDER BY game_date", connection
        )
    if data.empty:
        raise ValueError("O banco de dados não tem estatísticas de jogadores ainda.")
    data["game_date"] = pd.to_datetime(data["game_date"])
    data["is_home"] = data["is_home"].astype(bool)
    return data


def count_distinct_teams(path: Path = DEFAULT_DB_PATH) -> int:
    """Times distintos que aparecem em `games` (mandante ou visitante) — para
    o cartão "times cadastrados" da Visão Geral, sem precisar carregar os
    jogos inteiros em um DataFrame."""
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM (SELECT home_team AS team FROM games UNION SELECT away_team FROM games)"
        ).fetchone()[0]


def count_distinct_players(path: Path = DEFAULT_DB_PATH) -> int:
    """Jogadores distintos em `player_game_stats` — para o cartão "jogadores
    coletados" da Visão Geral."""
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_game_stats'"
        ).fetchall()
        if not tables:
            return 0
        return connection.execute(
            "SELECT COUNT(DISTINCT player_id) FROM player_game_stats"
        ).fetchone()[0]


def count_player_games(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]


def upsert_team_advanced_stats(advanced_stats: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere Rating oficiais novos, ignorando duplicatas (game_id, team)."""
    init_db(path)
    with sqlite3.connect(path) as connection:
        advanced_stats = apply_game_aliases(advanced_stats, connection)
        before = connection.execute("SELECT COUNT(*) FROM team_advanced_stats").fetchone()[0]
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO team_advanced_stats
                ({", ".join(_TEAM_ADVANCED_COLUMNS)})
            VALUES ({", ".join("?" for _ in _TEAM_ADVANCED_COLUMNS)})
            """,
            advanced_stats[_TEAM_ADVANCED_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM team_advanced_stats").fetchone()[0]
    return after - before


def read_team_advanced_stats(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=_TEAM_ADVANCED_COLUMNS)
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='team_advanced_stats'"
        ).fetchall()
        if not tables:
            return pd.DataFrame(columns=_TEAM_ADVANCED_COLUMNS)
        return pd.read_sql_query("SELECT * FROM team_advanced_stats", connection)


def count_team_advanced_stats(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='team_advanced_stats'"
        ).fetchall()
        if not tables:
            return 0
        return connection.execute("SELECT COUNT(*) FROM team_advanced_stats").fetchone()[0]
