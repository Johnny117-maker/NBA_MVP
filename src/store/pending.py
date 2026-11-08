"""Jogos com estatísticas avançadas ou titularidade pendentes e atualização da titularidade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .games import apply_game_aliases
from .schema import DEFAULT_DB_PATH, init_db


def _nba_pending_ids(rows: list, connection: sqlite3.Connection) -> list[str]:
    aliases = {canonical: alias for alias, canonical in connection.execute(
        "SELECT alias,canonical_id FROM game_id_aliases WHERE alias GLOB '00????????'"
    )}
    return [aliases.get(str(row[0]), str(row[0])) for row in rows
            if ":" not in str(row[0]) or str(row[0]) in aliases]


def games_missing_advanced_stats(path: Path = DEFAULT_DB_PATH, season: str | None = None) -> list:
    """Game_ids de `games` que ainda não têm Rating oficial coletado."""
    init_db(path)
    with sqlite3.connect(path) as connection:
        query = """
            SELECT DISTINCT g.game_id FROM games g
            WHERE g.game_id NOT IN (SELECT game_id FROM team_advanced_stats)
        """
        params: tuple = ()
        if season is not None:
            query += " AND g.season = ?"
            params = (season,)
        query += " ORDER BY g.game_date"
        rows = connection.execute(query, params).fetchall()
        return _nba_pending_ids(rows, connection)


def games_missing_starter_status(path: Path = DEFAULT_DB_PATH, season: str | None = None) -> list:
    """Game_ids de `player_game_stats` com pelo menos uma linha sem titularidade coletada."""
    init_db(path)
    with sqlite3.connect(path) as connection:
        query = "SELECT DISTINCT game_id FROM player_game_stats WHERE is_starter IS NULL"
        params: tuple = ()
        if season is not None:
            query += " AND season = ?"
            params = (season,)
        query += " ORDER BY game_date"
        rows = connection.execute(query, params).fetchall()
        return _nba_pending_ids(rows, connection)


def update_starter_status(rows: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Grava titularidade (titular/reserva) de jogadores num jogo já coletado.

    `rows` precisa ter as colunas `game_id`, `player_id`, `is_starter`. Só
    atualiza linhas que já existem em `player_game_stats` (o boxscore em si
    já foi coletado por `update_data.py`); não insere jogador novo. Retorna
    quantas linhas foram efetivamente atualizadas.
    """
    init_db(path)
    updated = 0
    with sqlite3.connect(path) as connection:
        rows = apply_game_aliases(rows, connection)
        for row in rows.itertuples(index=False):
            cursor = connection.execute(
                "UPDATE player_game_stats SET is_starter = ? WHERE game_id = ? AND player_id = ?",
                (int(row.is_starter), row.game_id, int(row.player_id)),
            )
            updated += cursor.rowcount
        connection.commit()
    return updated


def count_players_missing_starter_status(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM player_game_stats WHERE is_starter IS NULL"
        ).fetchone()[0]
