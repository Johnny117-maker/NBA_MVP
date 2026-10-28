"""Reconciliação conservadora de IDs: nomes completos únicos e IDs NBA oficiais."""

from __future__ import annotations

import re
import sqlite3
import unicodedata


def normalized_name(value: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", plain.casefold())


def reconcile_official_player(connection: sqlite3.Connection, player_id: int, name: str) -> None:
    if player_id <= 0:
        return
    candidates = connection.execute(
        "SELECT DISTINCT player_id,player_name FROM player_game_stats WHERE player_id < 0"
    ).fetchall()
    matches = {
        int(pid) for pid, known_name in candidates if normalized_name(known_name) == normalized_name(name)
    }
    if len(matches) != 1:
        return
    old = matches.pop()
    connection.execute(
        "UPDATE OR IGNORE player_game_stats SET player_id=? WHERE player_id=?", (player_id, old)
    )
    connection.execute(
        "DELETE FROM player_game_stats WHERE player_id=? AND game_id IN "
        "(SELECT game_id FROM player_game_stats WHERE player_id=?)",
        (old, player_id),
    )
    connection.execute("INSERT OR REPLACE INTO player_id_aliases VALUES (?,?)", (old, player_id))
    connection.execute("UPDATE player_predictions SET player_id=? WHERE player_id=?", (player_id, old))
