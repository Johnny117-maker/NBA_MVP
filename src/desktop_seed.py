"""Base histórica pública: estatísticas e acervo, sem previsões, chaves ou caches privados."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .live_store import save_live_games, set_state, state_path
from .live_types import LiveGame
from .shot_storage import init_shots_db
from .store import init_db


def build_seed(
    source: Path,
    target: Path,
    *,
    player_limit: int | None = None,
    shot_limit: int | None = None,
    start_season: str = "2021-22",
    include_history: bool = True,
) -> dict:
    if target.exists():
        raise FileExistsError("A base inicial de destino já existe; use uma nova pasta de compilação.")
    if (player_limit is not None and player_limit <= 0) or (shot_limit is not None and shot_limit < 0):
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
            "AND season>=? GROUP BY date(game_date) ORDER BY date(game_date) DESC",
            (start_season,),
        ).fetchall()
        selected, total = [], 0
        for day, count in dates:
            if player_limit is not None and total + count > player_limit:
                break
            selected.append(day)
            total += count
        earliest = min(selected) if selected else "9999-12-31"
        queries = {
            "games": ("SELECT * FROM games WHERE season>=?", (start_season,)),
            "player_game_stats": (
                "SELECT * FROM player_game_stats WHERE season>=? "
                + ("AND minutes>0 AND date(game_date)>=? " if player_limit is not None else "")
                + "ORDER BY game_date,game_id,player_id",
                (start_season, earliest) if player_limit is not None else (start_season,),
            ),
            "game_id_aliases": ("SELECT * FROM game_id_aliases", ()),
            "player_id_aliases": ("SELECT * FROM player_id_aliases", ()),
            "team_advanced_stats": ("SELECT * FROM team_advanced_stats", ()),
            "player_shots": (
                "SELECT * FROM player_shots WHERE season>=? "
                "ORDER BY game_date DESC,game_id DESC,game_event_id DESC"
                + (" LIMIT ?" if shot_limit is not None else ""),
                (start_season, shot_limit) if shot_limit is not None else (start_season,),
            ),
        }
        with sqlite3.connect(target) as output:
            for table, (query, params) in queries.items():
                if table not in available:
                    continue
                cursor = original.execute(query, params)
                names = [entry[0] for entry in cursor.description]
                count = 0
                while rows := cursor.fetchmany(10000):
                    output.executemany(
                        f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                        rows,
                    )
                    count += len(rows)
                counts[table] = count
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
    archive = source.with_name("nba_history.sqlite")
    if archive.exists() and include_history:
        with sqlite3.connect(archive.resolve().as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(target.with_name("nba_history.sqlite")) as output:
                original.backup(output)
                output.execute("DELETE FROM history_state WHERE key NOT LIKE 'matchups:%'")
            entries = original.execute("SELECT source_url,relative_path FROM assets").fetchall()
        base = (source.parent / "history").resolve()
        files = 0
        for url, relative in entries:
            file = (base / relative).resolve()
            if not str(url).startswith(
                "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
            ):
                continue
            if not file.is_relative_to(base) or not file.is_file():
                raise ValueError("Arquivo do acervo fora do diretório de dados públicos.")
            destination = target.parent / "history" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)
            files += 1
        counts["public_archive_files"] = files
    counts["bytes"] = target.stat().st_size
    return counts
