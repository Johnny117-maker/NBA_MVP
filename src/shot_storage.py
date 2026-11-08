from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .shot_connector import SHOT_COLUMNS
from .store import DEFAULT_DB_PATH, apply_game_aliases

_PLAYER_SHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_shots (
    player_id INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    game_id TEXT NOT NULL,
    game_event_id INTEGER NOT NULL,
    season TEXT NOT NULL,
    game_date TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    team_name TEXT NOT NULL,
    opponent TEXT,
    period INTEGER NOT NULL,
    minutes_remaining INTEGER NOT NULL,
    seconds_remaining INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    action_type TEXT NOT NULL,
    shot_type TEXT NOT NULL,
    shot_zone_basic TEXT NOT NULL,
    shot_zone_area TEXT NOT NULL,
    shot_zone_range TEXT NOT NULL,
    shot_distance REAL NOT NULL,
    loc_x REAL NOT NULL,
    loc_y REAL NOT NULL,
    loc_x_ft REAL NOT NULL,
    loc_y_ft REAL NOT NULL,
    shot_attempted INTEGER NOT NULL,
    shot_made INTEGER NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (player_id, game_id, game_event_id)
);
"""

# A chave primária é ordenada (player_id, game_id, game_event_id) — não ajuda
# a checagem "esse player_id+season já tem alguma linha?" de
# `players_missing_shots`, que sem este índice faz uma varredura completa de
# `player_shots` para cada par (player_id, season) verificado. Em ~1,7 milhão
# de linhas já coletadas, isso levava mais de 80 segundos; com o índice, é
# quase instantâneo.
_PLAYER_SHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_player_shots_player_season
ON player_shots (player_id, season);
"""


def init_shots_db(path: Path = DEFAULT_DB_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(_PLAYER_SHOTS_SCHEMA + _PLAYER_SHOTS_INDEX)


def upsert_player_shots(shots: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere arremessos novos, ignorando duplicatas (player_id, game_id, game_event_id)."""
    init_shots_db(path)
    if shots.empty:
        return 0

    rows = shots.copy()
    rows["game_date"] = rows["game_date"].astype(str)

    with sqlite3.connect(path) as connection:
        rows = apply_game_aliases(rows, connection)
        before = connection.execute("SELECT COUNT(*) FROM player_shots").fetchone()[0]
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO player_shots
                ({", ".join(SHOT_COLUMNS)})
            VALUES ({", ".join("?" for _ in SHOT_COLUMNS)})
            """,
            rows[SHOT_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM player_shots").fetchone()[0]
    return after - before


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchall()
    return bool(rows)


def read_player_shots(
    path: Path = DEFAULT_DB_PATH,
    player_id: int | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=SHOT_COLUMNS)
    with sqlite3.connect(path) as connection:
        if not _table_exists(connection, "player_shots"):
            return pd.DataFrame(columns=SHOT_COLUMNS)

        query = "SELECT * FROM player_shots WHERE 1=1"
        params: list = []
        if player_id is not None:
            query += " AND player_id = ?"
            params.append(int(player_id))
        if season is not None:
            query += " AND season = ?"
            params.append(season)
        data = pd.read_sql_query(query, connection, params=params)

    if not data.empty:
        data["game_date"] = pd.to_datetime(data["game_date"])
        data["shot_attempted"] = data["shot_attempted"].astype(bool)
        data["shot_made"] = data["shot_made"].astype(bool)
    return data


# Colunas usadas por `src/shot_features.py`/`src/shot_model/` para estatísticas
# de referência e treino dos modelos de zona. Bem menos que as 26 de
# `SHOT_COLUMNS` — sobretudo menos colunas de texto (7 em vez de 12), que são
# o gargalo de memória ao carregar/cachear a base inteira (com a coleta em
# larga escala, `player_shots` já passa de 1 milhão de linhas).
ZONE_REFERENCE_COLUMNS = [
    "player_id",
    "player_name",
    "game_id",
    "game_date",
    "season",
    "team_name",
    "opponent",
    "shot_zone_basic",
    "shot_type",
    "shot_distance",
    "shot_attempted",
    "shot_made",
]


def read_shots_for_zone_reference(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Todos os arremessos já coletados, mas só as colunas de `ZONE_REFERENCE_COLUMNS`.

    Para cálculos que precisam olhar a base inteira (referência de liga,
    defesa por adversário, treino dos modelos de zona) — carregar as 26
    colunas de `player_shots` só para descartar 14 delas (coordenadas,
    período, tipo de ação etc.) desperdiça memória proporcional ao tamanho da
    base, que só cresce.
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=ZONE_REFERENCE_COLUMNS)
    with sqlite3.connect(path) as connection:
        if not _table_exists(connection, "player_shots"):
            return pd.DataFrame(columns=ZONE_REFERENCE_COLUMNS)
        query = f"SELECT {', '.join(ZONE_REFERENCE_COLUMNS)} FROM player_shots"
        data = pd.read_sql_query(query, connection)

    if not data.empty:
        data["game_date"] = pd.to_datetime(data["game_date"])
        data["shot_attempted"] = data["shot_attempted"].astype(bool)
        data["shot_made"] = data["shot_made"].astype(bool)
    return data


def list_players_with_shots(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Jogadores distintos com pelo menos um arremesso coletado (`player_id`,
    `player_name`) — para popular um seletor sem carregar nenhuma linha de
    arremesso em si.
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["player_id", "player_name"])
    with sqlite3.connect(path) as connection:
        if not _table_exists(connection, "player_shots"):
            return pd.DataFrame(columns=["player_id", "player_name"])
        return pd.read_sql_query(
            "SELECT DISTINCT player_id, player_name FROM player_shots ORDER BY player_name",
            connection,
        )


def count_player_shots(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        if not _table_exists(connection, "player_shots"):
            return 0
        return connection.execute("SELECT COUNT(*) FROM player_shots").fetchone()[0]


def players_missing_shots(
    path: Path = DEFAULT_DB_PATH, season: str | None = None
) -> list[tuple[int, str, str]]:
    """Pares (player_id, player_name, season) já presentes em `player_game_stats`
    que ainda não têm nenhum arremesso salvo em `player_shots`.
    """
    path = Path(path)
    if not path.exists():
        return []
    init_shots_db(path)
    with sqlite3.connect(path) as connection:
        if not _table_exists(connection, "player_game_stats"):
            return []

        query = """
            SELECT DISTINCT p.player_id, p.player_name, p.season
            FROM player_game_stats p
            WHERE p.player_id > 0 AND NOT EXISTS (
                SELECT 1 FROM player_shots s
                WHERE s.player_id = p.player_id AND s.season = p.season
            )
        """
        params: list = []
        if season is not None:
            query += " AND p.season = ?"
            params.append(season)
        query += " ORDER BY p.season, p.player_id"
        rows = connection.execute(query, params).fetchall()
    return [(int(row[0]), row[1], row[2]) for row in rows]
