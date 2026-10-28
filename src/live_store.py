"""Estado de coleta separado do histórico: ticks do relógio não invalidam modelos."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .entity_ids import normalized_name, reconcile_official_player
from .live_types import STAT_FIELDS, LiveGame, LivePlayer, utc_now
from .nba_teams import TEAM_ABBREVIATION_TO_NAME
from .store import _PLAYER_GAME_COLUMNS, init_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_games (game_key TEXT PRIMARY KEY, day TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS player_aliases (
 provider TEXT, external_id TEXT, canonical_id INTEGER NOT NULL,
 PRIMARY KEY(provider,external_id));
CREATE TABLE IF NOT EXISTS http_cache (key TEXT PRIMARY KEY, body TEXT, fetched_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_usage (provider TEXT, period TEXT, used INTEGER NOT NULL,
 PRIMARY KEY(provider,period));
CREATE TABLE IF NOT EXISTS sync_lease (id INTEGER PRIMARY KEY, owner TEXT, expires REAL);
"""


def state_path(db_path: str | Path) -> Path:
    db_path = Path(db_path)
    return db_path.with_name(db_path.stem + "_sync.sqlite")


def connect_state(db_path: str | Path) -> sqlite3.Connection:
    path = state_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.executescript(SCHEMA)
    return connection


def set_state(db_path: str | Path, key: str, value: object) -> None:
    with connect_state(db_path) as connection:
        connection.execute("INSERT OR REPLACE INTO sync_state VALUES (?,?)", (key, json.dumps(value)))


def get_state(db_path: str | Path, key: str, default=None):
    if not state_path(db_path).exists():
        return default
    with connect_state(db_path) as connection:
        row = connection.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def acquire_lease(db_path: str | Path, owner: str, ttl: int = 180) -> bool:
    now = utc_now().timestamp()
    with connect_state(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT owner,expires FROM sync_lease WHERE id=1").fetchone()
        if row and row[0] != owner and row[1] > now and _owner_alive(row[0]):
            return False
        connection.execute("INSERT OR REPLACE INTO sync_lease VALUES (1,?,?)", (owner, now + ttl))
    return True


def _owner_alive(owner: str) -> bool:
    """Uma reinicialização não aguarda a expiração da trava de um processo encerrado."""
    raw = owner.split(":", 1)[0]
    if not raw.isdigit() or int(raw) <= 0:
        return True
    pid = int(raw)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Acesso negado: preserve a trava.
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def live_schedule(db_path: str | Path, day: str) -> pd.DataFrame:
    from .nba_schedule import SCHEDULE_COLUMNS

    games = read_live_games(db_path, day)
    return pd.DataFrame(
        [
            {
                "game_id": g.external_id,
                "game_date": pd.Timestamp(g.day),
                "game_datetime_utc": pd.to_datetime(g.kickoff, utc=True) if g.kickoff else pd.NaT,
                "game_status": {"pre": 1, "live": 2, "final": 3}.get(g.state, 4),
                "game_status_text": {"pre": "Agendado", "live": "Em andamento", "final": "Encerrado"}.get(
                    g.state, "Indisponível"
                ),
                "game_label": "",
                "home_team_tricode": g.home,
                "away_team_tricode": g.away,
                "home_team_name": TEAM_ABBREVIATION_TO_NAME[g.home],
                "away_team_name": TEAM_ABBREVIATION_TO_NAME[g.away],
                "arena_name": "",
                "schedule_source": g.source + (" (arquivo periódico)" if g.archive else " (consulta direta)"),
            }
            for g in games
        ],
        columns=SCHEDULE_COLUMNS,
    )


def release_lease(db_path: str | Path, owner: str) -> None:
    with connect_state(db_path) as connection:
        connection.execute("DELETE FROM sync_lease WHERE id=1 AND owner=?", (owner,))


def reserve_usage(db_path: str | Path, provider: str, costs: dict[str, tuple[int, int]]) -> bool:
    """Reserva atômica antes da consulta, inclusive quando a resposta falhar."""
    with connect_state(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for period, (cost, limit) in costs.items():
            row = connection.execute(
                "SELECT used FROM api_usage WHERE provider=? AND period=?", (provider, period)
            ).fetchone()
            if (row[0] if row else 0) + cost > limit:
                return False
        for period, (cost, _) in costs.items():
            connection.execute(
                "INSERT INTO api_usage VALUES (?,?,?) ON CONFLICT(provider,period) "
                "DO UPDATE SET used=used+excluded.used",
                (provider, period, cost),
            )
    return True


def cache_get(db_path: str | Path, key: str, ttl: int) -> str | None:
    with connect_state(db_path) as connection:
        row = connection.execute("SELECT body,fetched_at FROM http_cache WHERE key=?", (key,)).fetchone()
    return row[0] if row and utc_now().timestamp() - row[1] < ttl else None


def cache_put(db_path: str | Path, key: str, body: str) -> None:
    with connect_state(db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO http_cache VALUES (?,?,?)", (key, body, utc_now().timestamp())
        )
        connection.execute(
            "DELETE FROM http_cache WHERE fetched_at < ?", (utc_now().timestamp() - 7 * 86400,)
        )


def clear_archive_cache(db_path: str | Path) -> None:
    with connect_state(db_path) as connection:
        connection.execute("DELETE FROM http_cache WHERE key LIKE 'SportsDataverse/ESPN%'")


def save_live_games(db_path: str | Path, games: list[LiveGame], replace_day: str | None = None) -> None:
    with connect_state(db_path) as connection:
        if replace_day is not None:
            keys = [game.key for game in games]
            if keys:
                connection.execute(
                    f"DELETE FROM live_games WHERE day=? AND game_key NOT IN ({','.join('?' for _ in keys)})",
                    (replace_day, *keys),
                )
            else:
                connection.execute("DELETE FROM live_games WHERE day=?", (replace_day,))
        for game in games:
            # Um arquivo de temporada não substitui uma consulta direta recente.
            previous = connection.execute(
                "SELECT payload FROM live_games WHERE game_key=?", (game.key,)
            ).fetchone()
            if previous and game.archive:
                old = LiveGame.from_dict(json.loads(previous[0]))
                age = (utc_now() - datetime.fromisoformat(old.fetched_at)).total_seconds()
                if not old.archive and age < 300:
                    continue
            if previous and not game.kickoff:
                game.kickoff = LiveGame.from_dict(json.loads(previous[0])).kickoff
            connection.execute(
                "INSERT OR REPLACE INTO live_games VALUES (?,?,?)",
                (game.key, game.day, json.dumps(game.to_dict())),
            )
        cutoff = datetime.fromtimestamp(utc_now().timestamp() - 7 * 86400, UTC).date().isoformat()
        connection.execute("DELETE FROM live_games WHERE day < ?", (cutoff,))


def read_live_games(db_path: str | Path, day: str) -> list[LiveGame]:
    if not state_path(db_path).exists():
        return []
    with connect_state(db_path) as connection:
        rows = connection.execute("SELECT payload FROM live_games WHERE day=? ORDER BY game_key", (day,))
        return [LiveGame.from_dict(json.loads(row[0])) for row in rows]


def resolve_player(
    db_path: str | Path,
    source: str,
    player: LivePlayer,
    crosswalk: dict[str, int] | None = None,
    known_names: dict[str, set[int]] | None = None,
) -> int:
    if source == "NBA" and player.external_id.isdigit():
        with sqlite3.connect(db_path) as history:
            reconcile_official_player(history, int(player.external_id), player.name)
        return int(player.external_id)
    provider = "ESPN" if "ESPN" in source else source
    with connect_state(db_path) as state:
        alias = state.execute(
            "SELECT canonical_id FROM player_aliases WHERE provider=? AND external_id=?",
            (provider, player.external_id),
        ).fetchone()
        if alias:
            with sqlite3.connect(db_path) as history:
                official = history.execute(
                    "SELECT canonical_id FROM player_id_aliases WHERE alias=?", (int(alias[0]),)
                ).fetchone()
            return int(official[0]) if official else int(alias[0])
        candidate = (crosswalk or {}).get(player.external_id)
        if candidate is None:
            known_names = known_names if known_names is not None else player_identity_index(db_path)
            matches = known_names.get(normalized_name(player.name), set()).copy()
            if len(matches) == 1:
                candidate = matches.pop()
        if candidate is None:
            minimum = state.execute("SELECT MIN(canonical_id) FROM player_aliases").fetchone()[0]
            with sqlite3.connect(db_path) as history:
                historical_min = history.execute("SELECT MIN(player_id) FROM player_game_stats").fetchone()[0]
            candidate = min(-1, int(minimum or 0) - 1, int(historical_min or 0) - 1)
        state.execute("INSERT INTO player_aliases VALUES (?,?,?)", (provider, player.external_id, candidate))
        return candidate


def player_identity_index(db_path: str | Path) -> dict[str, set[int]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT DISTINCT player_id,player_name FROM player_game_stats").fetchall()
    result: dict[str, set[int]] = {}
    for pid, name in rows:
        result.setdefault(normalized_name(name), set()).add(int(pid))
    return result


def validate_final(game: LiveGame) -> None:
    if game.state != "final" or not game.regular_season:
        raise ValueError("Somente partidas encerradas da temporada regular entram no histórico.")
    if game.home not in TEAM_ABBREVIATION_TO_NAME or game.away not in TEAM_ABBREVIATION_TO_NAME:
        raise ValueError("Equipe não reconhecida.")
    if game.home_score is None or game.away_score is None or game.home_score == game.away_score:
        raise ValueError("Placar final ausente ou empatado.")
    active = [p for p in game.players if (p.minutes or 0) > 0]
    if any(not p.name.strip() or not p.external_id.strip() for p in active):
        raise ValueError("Boxscore incompleto: identidade de jogador ausente.")
    if len({p.external_id for p in active}) != len(active):
        raise ValueError("Boxscore inconsistente: jogador duplicado.")
    for team, score in ((game.home, game.home_score), (game.away, game.away_score)):
        players = [p for p in game.players if p.team == team and (p.minutes or 0) > 0]
        if len(players) < 5:
            raise ValueError("Boxscore incompleto: faltam atletas com minutos.")
        if any(
            p.stats.get(stat) is None or float(p.stats[stat] or 0) < 0
            for p in players
            for stat in STAT_FIELDS
        ):
            raise ValueError("Boxscore incompleto: estatística ausente ou negativa.")
        if sum(float(p.stats["pts"] or 0) for p in players) != score:
            raise ValueError("Soma dos pontos dos jogadores diverge do placar final.")
        for player in players:
            stats = player.stats
            if (
                stats["reb"] != float(stats["oreb"] or 0) + float(stats["dreb"] or 0)
                or float(stats["fgm"] or 0) > float(stats["fga"] or 0)
                or float(stats["fg3m"] or 0) > float(stats["fgm"] or 0)
                or stats["pts"]
                != 2 * float(stats["fgm"] or 0) + float(stats["fg3m"] or 0) + float(stats["ftm"] or 0)
            ):
                raise ValueError("Boxscore inconsistente: arremessos, pontos ou rebotes divergentes.")
        duration = 240 + max(0, game.period - 4) * 25
        total_minutes = sum(float(p.minutes or 0) for p in players)
        if abs(total_minutes - duration) > 10:
            raise ValueError("Boxscore incompleto: minutos da equipe inconsistentes.")


def persist_final(
    db_path: str | Path,
    game: LiveGame,
    crosswalk: dict[str, int] | None = None,
    known_names: dict[str, set[int]] | None = None,
) -> bool:
    validate_final(game)
    init_db(Path(db_path))
    for player in game.players:
        if (player.minutes or 0) > 0:
            player.canonical_id = resolve_player(db_path, game.source, player, crosswalk, known_names)
    # Datas de consulta não entram no hash: uma repetição não invalida os modelos.
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "home": game.home_score,
                "away": game.away_score,
                "players": sorted(
                    (p.canonical_id, p.minutes, sorted(p.stats.items()), p.starter)
                    for p in game.players
                    if (p.minutes or 0) > 0
                ),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with sqlite3.connect(db_path, timeout=15) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ingestion_provenance "
            "(game_id TEXT PRIMARY KEY, source TEXT, fingerprint TEXT, updated_at TEXT)"
        )
        existing = connection.execute(
            "SELECT game_id FROM games WHERE date(game_date)=? AND home_team=? AND away_team=? LIMIT 1",
            (game.day, TEAM_ABBREVIATION_TO_NAME[game.home], TEAM_ABBREVIATION_TO_NAME[game.away]),
        ).fetchone()
        game_id = (
            existing[0]
            if existing
            else (
                game.external_id
                if game.source == "NBA"
                else "espn:" + game.external_id
                if "ESPN" in game.source
                else game.source + ":" + game.external_id
            )
        )
        old_context = connection.execute(
            "SELECT date(game_date),home_team,away_team FROM games WHERE game_id=?", (game_id,)
        ).fetchone()
        expected_context = (
            game.day,
            TEAM_ABBREVIATION_TO_NAME[game.home],
            TEAM_ABBREVIATION_TO_NAME[game.away],
        )
        if old_context is not None and old_context != expected_context:
            raise ValueError("Identificador de partida associado a outra data ou equipes.")
        alias = (
            game.external_id
            if game.source == "NBA"
            else (
                "espn:" + game.external_id if "ESPN" in game.source else game.source + ":" + game.external_id
            )
        )
        if alias != game_id:
            connection.execute("INSERT OR REPLACE INTO game_id_aliases VALUES (?,?)", (alias, game_id))
        previous = connection.execute(
            "SELECT source,fingerprint FROM ingestion_provenance WHERE game_id=?", (game_id,)
        ).fetchone()
        priorities = {
            "NBA": 30,
            "NBA (preexistente)": 30,
            "ESPN": 20,
            "API-Sports": 15,
            "balldontlie": 15,
            "SportsDataverse/ESPN": 10,
        }
        if previous and previous[1] == fingerprint:
            if priorities.get(game.source, 0) > priorities.get(previous[0], 30):
                connection.execute(
                    "UPDATE ingestion_provenance SET source=?,updated_at=? WHERE game_id=?",
                    (game.source, utc_now().isoformat(), game_id),
                )
            return False
        if previous and priorities.get(previous[0], 30) > priorities.get(game.source, 0):
            return False
        # Dados oficiais preexistentes não são sobrescritos por um arquivo alternativo.
        official_existing = (
            game.source != "NBA"
            and existing is not None
            and (previous is None or previous[0] == "NBA (preexistente)")
        )
        if not official_existing:
            connection.execute(
                "INSERT INTO games VALUES (?,?,?,?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET "
                "home_points=excluded.home_points,away_points=excluded.away_points",
                (
                    game_id,
                    game.day,
                    game.season,
                    TEAM_ABBREVIATION_TO_NAME[game.home],
                    TEAM_ABBREVIATION_TO_NAME[game.away],
                    game.home_score,
                    game.away_score,
                ),
            )
        columns = [*_PLAYER_GAME_COLUMNS, "is_starter"]
        updates = ",".join(f"{col}=excluded.{col}" for col in columns if col not in {"game_id", "player_id"})
        conflict = "DO NOTHING" if official_existing else "DO UPDATE SET " + updates
        for player in game.players:
            if (player.minutes or 0) <= 0:
                continue
            record = {
                "game_id": game_id,
                "player_id": player.canonical_id,
                "game_date": game.day,
                "season": game.season,
                "player_name": player.name,
                "team": player.team,
                "opponent": game.away if player.team == game.home else game.home,
                "is_home": int(player.team == game.home),
                "minutes": player.minutes,
                **{key: int(player.stats[key] or 0) for key in STAT_FIELDS},
                "is_starter": None if player.starter is None else int(player.starter),
            }
            connection.execute(
                f"INSERT INTO player_game_stats ({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)}) "
                f"ON CONFLICT(game_id,player_id) {conflict}",
                tuple(record[col] for col in columns),
            )
        connection.execute(
            "INSERT OR REPLACE INTO ingestion_provenance VALUES (?,?,?,?)",
            (
                game_id,
                "NBA (preexistente)" if official_existing else game.source,
                fingerprint,
                utc_now().isoformat(),
            ),
        )
    return True
