"""Base inicial compacta: somente estatísticas públicas, sem previsões, chaves ou caches privados."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .live_store import save_live_games, set_state, state_path
from .live_types import LiveGame
from .shot_storage import init_shots_db
from .store import init_db


def build_seed(source: Path, target: Path, *, player_limit: int = 40000, shot_limit: int = 20000) -> dict:
    if target.exists():
        raise FileExistsError("A base inicial de destino já existe; use uma nova pasta de compilação.")
    if player_limit <= 0 or shot_limit < 0:
        raise ValueError("Os limites da base inicial devem ser positivos.")
    target.parent.mkdir(parents=True, exist_ok=True)
    init_db(target)
    init_shots_db(target)
    counts = {}
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        original.execute("BEGIN")
        available = {r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        dates = original.execute(
            "SELECT date(game_date),COUNT(*) FROM player_game_stats WHERE minutes>0 "
            "GROUP BY date(game_date) ORDER BY date(game_date) DESC"
        ).fetchall()
        selected, total = [], 0
        for day, count in dates:
            if total + count > player_limit:
                break
            selected.append(day)
            total += count
        earliest = min(selected) if selected else "9999-12-31"
        queries = {
            "games": ("SELECT * FROM games", ()),
            "player_game_stats": (
                "SELECT * FROM player_game_stats WHERE minutes>0 AND date(game_date)>=? "
                "ORDER BY game_date,game_id,player_id",
                (earliest,),
            ),
            "game_id_aliases": ("SELECT * FROM game_id_aliases", ()),
            "player_id_aliases": ("SELECT * FROM player_id_aliases", ()),
            "team_advanced_stats": ("SELECT * FROM team_advanced_stats", ()),
            "player_shots": (
                "SELECT * FROM player_shots ORDER BY game_date DESC,game_id DESC,game_event_id DESC LIMIT ?",
                (shot_limit,),
            ),
        }
        with sqlite3.connect(target) as output:
            for table, (query, params) in queries.items():
                if table not in available:
                    continue
                cursor = original.execute(query, params)
                names = [entry[0] for entry in cursor.description]
                rows = cursor.fetchall()
                if rows:
                    output.executemany(
                        f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                        rows,
                    )
                counts[table] = len(rows)
    # Somente a lista de jogos é transferida. Cotações, consumo de APIs, credenciais,
    # travas e fotografias pessoais não fazem parte do pacote distribuível.
    if state_path(source).exists():
        with sqlite3.connect(state_path(source)) as state:
            for (body,) in state.execute("SELECT payload FROM live_games"):
                game = LiveGame.from_dict(json.loads(body))
                game.archive = True
                game.players = []
                if game.state == "live":
                    game.state = "unavailable"
                save_live_games(target, [game])
            row = state.execute("SELECT value FROM sync_state WHERE key='status'").fetchone()
            if row:
                original_status = json.loads(row[0])
                status = {
                    key: original_status[key]
                    for key in ("season", "archive_latest_game", "archive_success_at")
                    if key in original_status
                }
                status["live_available"] = False
                set_state(target, "status", status)
    counts["bytes"] = target.stat().st_size
    return counts
