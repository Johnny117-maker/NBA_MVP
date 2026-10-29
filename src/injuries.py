"""Disponibilidade pública: snapshots atômicos, atualização independente e fonte explícita."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pandas as pd

from .entity_ids import normalized_name
from .history_sources import CATALOG_URL, PublicAsset, download_asset
from .history_store import history_root, read_assets
from .live_providers import ESPN_BASE, FeedClient, ProviderError, team_code
from .live_store import connect_state, get_state
from .live_types import current_season, utc_now

INTERVAL = 300
STATUS = {
    "out": "Fora",
    "day-to-day": "Dia a dia",
    "questionable": "Questionável",
    "doubtful": "Improvável",
    "probable": "Provável",
    "suspension": "Suspenso",
    "suspended": "Suspenso",
    "injured reserve": "Reserva por lesão",
    "active": "Disponível",
    "available": "Disponível",
}
COLUMNS = [
    "athlete_id",
    "player",
    "team",
    "position",
    "status",
    "status_raw",
    "injury",
    "reported_at",
    "estimated_return",
    "note",
]
_lock = threading.Lock()
_workers: dict[str, tuple[threading.Thread, threading.Event]] = {}


def _text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _row(athlete_id, name, team, position, status, injury, reported, estimated, note) -> dict:
    if not str(athlete_id).isdigit() or not name or not team:
        raise ValueError("Boletim com atleta ou equipe não identificado.")
    return dict(
        zip(
            COLUMNS,
            [
                str(athlete_id),
                name,
                team,
                position,
                STATUS.get(status.lower(), "Não classificado"),
                status,
                injury,
                reported,
                estimated,
                note,
            ],
            strict=True,
        )
    )


def parse_espn_injuries(payload: dict) -> pd.DataFrame:
    if not isinstance(payload, dict) or not isinstance(payload.get("injuries"), list):
        raise ValueError("Formato do boletim ESPN mudou; lista anterior preservada.")
    rows = []
    for group in payload["injuries"]:
        if not isinstance(group, dict) or not isinstance(group.get("team", {}), dict):
            raise ValueError("Equipe inválida no boletim ESPN.")
        team = group.get("team", {})
        code = team_code(team.get("abbreviation") or team.get("displayName") or group.get("displayName"))
        if not isinstance(group.get("injuries"), list):
            raise ValueError("Lista de lesões da equipe ausente.")
        for item in group["injuries"]:
            if not isinstance(item, dict):
                raise ValueError("Registro de lesão inválido.")
            athlete, detail = item.get("athlete", {}), item.get("details", {})
            if not isinstance(athlete, dict) or not isinstance(detail, dict):
                raise ValueError("Atleta ou detalhes de lesão inválidos.")
            status = item.get("status", "")
            if isinstance(status, dict):
                status = status.get("description", status.get("name", ""))
            rows.append(
                _row(
                    athlete.get("id", ""),
                    athlete.get("displayName", ""),
                    code,
                    athlete.get("position", {}).get("abbreviation", ""),
                    str(status),
                    " · ".join(str(detail[k]) for k in ("side", "type") if detail.get(k)),
                    item.get("date", ""),
                    detail.get("returnDate", ""),
                    item.get("shortComment", ""),
                )
            )
    return pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(["team", "athlete_id"], keep="last")


def parse_archive_injuries(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    required = {"as_of_date", "athlete_id", "athlete_display_name", "team_display_name", "status"}
    if not required.issubset(frame) or frame.empty:
        raise ValueError("Snapshot de lesões sem data, atletas ou equipes.")
    dates = pd.to_datetime(frame.as_of_date, utc=True, errors="coerce")
    if dates.isna().any() or dates.max().date() > utc_now().date():
        raise ValueError("Snapshot de lesões com data inválida.")
    # Um atleta ausente do último snapshot não permanece artificialmente lesionado.
    latest = dates.max()
    rows = []
    for row in frame.loc[dates.eq(latest)].to_dict("records"):
        rows.append(
            _row(
                _text(row["athlete_id"]),
                _text(row["athlete_display_name"]),
                team_code(row["team_display_name"]),
                _text(row.get("athlete_position")),
                _text(row["status"]),
                " · ".join(filter(None, (_text(row.get("detail_side")), _text(row.get("detail_type"))))),
                _text(row.get("injury_date")),
                _text(row.get("detail_return_date")),
                _text(row.get("short_comment")),
            )
        )
    return pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(["team", "athlete_id"], keep="last"), str(
        latest.date()
    )


def injury_snapshot(db_path: str | Path) -> tuple[pd.DataFrame, dict]:
    snapshot = get_state(db_path, "injury_snapshot", {})
    state = {key: val for key, val in snapshot.items() if key != "rows"}
    state.update(get_state(db_path, "injury_attempt", {}))
    source_date = pd.to_datetime(state.get("source_updated"), utc=True, errors="coerce")
    state["stale"] = bool(
        pd.isna(source_date)
        or (utc_now() - source_date).total_seconds() > (21600 if state.get("daily_snapshot") else 900)
    )
    return pd.DataFrame(snapshot.get("rows", []), columns=COLUMNS), state


def filter_pick_players(
    players: pd.DataFrame, injuries: pd.DataFrame, *, name_column="player_name"
) -> pd.DataFrame:
    """Retira registros de lesão/dúvida antes do ranking, sem comparar IDs ESPN com NBA.

    O nome completo normalizado também cobre atletas cuja equipe histórica ainda
    não reflete uma transferência. Não usa iniciais, busca parcial ou fuzzy match.
    """
    if players.empty or injuries.empty:
        return players.copy()
    blocked = {
        normalized_name(str(row.player)) for row in injuries.itertuples() if str(row.status) != "Disponível"
    }
    names = players[name_column].astype(str).map(normalized_name)
    return players.loc[~names.isin(blocked)].copy()


def current_pick_players(db_path: str | Path, players: pd.DataFrame) -> pd.DataFrame:
    rows, state = injury_snapshot(db_path)
    # Sem boletim recebido, não apresenta uma seleção como verificada por lesões.
    if not state.get("source"):
        return players.iloc[:0].copy()
    return filter_pick_players(players, rows)


def refresh_injuries(db_path: str | Path, *, force: bool = False, client=None) -> dict:
    now = utc_now()
    with connect_state(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT value FROM sync_state WHERE key='injury_next_poll'").fetchone()
        next_poll = float(json.loads(row[0])) if row else 0
        # Inclusive cliques manuais respeitam 30 segundos entre consultas da mesma base.
        if now.timestamp() < next_poll - (INTERVAL - 30 if force else 0):
            row = connection.execute("SELECT value FROM sync_state WHERE key='injury_attempt'").fetchone()
            return json.loads(row[0]) if row else {}
        connection.execute(
            "INSERT OR REPLACE INTO sync_state VALUES ('injury_next_poll',?)",
            (json.dumps(now.timestamp() + INTERVAL),),
        )
    client = client or FeedClient(db_path)
    errors = []
    result = None
    try:
        rows = parse_espn_injuries(client.get("ESPN", ESPN_BASE + "/injuries"))
        result = dict(
            rows=rows.to_dict("records"),
            source="ESPN",
            source_url=ESPN_BASE + "/injuries",
            source_updated=now.isoformat(),
            source_as_of=now.isoformat(),
            daily_snapshot=False,
        )
    except (ProviderError, ValueError, KeyError, TypeError) as error:
        errors.append(f"ESPN: {type(error).__name__}")
    if result is None:
        year = int(current_season()[:4]) + 1
        try:
            release = client.get(
                "SportsDataverse/ESPN", CATALOG_URL + "/tags/espn_nba_injuries", ttl=0 if force else INTERVAL
            )
            asset = next(item for item in release["assets"] if item["name"] == f"injuries_{year}.parquet")
            expected = (
                "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
                f"espn_nba_injuries/injuries_{year}.parquet"
            )
            if asset["browser_download_url"] != expected:
                raise ValueError("Origem inesperada no catálogo de lesões.")
            download_asset(
                db_path,
                PublicAsset(
                    "espn_nba_injuries",
                    asset["name"],
                    year,
                    expected,
                    asset["updated_at"],
                    int(asset["size"]),
                ),
            )
        except (ProviderError, ValueError, KeyError, TypeError, StopIteration, OSError) as error:
            errors.append(f"Acervo: {type(error).__name__}")
        assets = read_assets(db_path)
        selected = (
            assets.loc[assets.tag.eq("espn_nba_injuries") & assets.year.eq(year)]
            if not assets.empty
            else assets
        )
        if not selected.empty:
            try:
                asset = selected.iloc[0]
                rows, as_of = parse_archive_injuries(
                    pd.read_parquet(history_root(db_path) / asset.relative_path)
                )
                result = dict(
                    rows=rows.to_dict("records"),
                    source="SportsDataverse / ESPN",
                    source_url=asset.source_url,
                    source_updated=asset.source_updated,
                    source_as_of=as_of,
                    daily_snapshot=True,
                )
            except (ValueError, KeyError, TypeError, OSError) as error:
                errors.append(f"Arquivo local: {type(error).__name__}")
    attempt = dict(checked_at=now.isoformat(), errors=errors, available=result is not None)
    with connect_state(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if result is not None:
            saved = connection.execute("SELECT value FROM sync_state WHERE key='injury_snapshot'").fetchone()
            previous = json.loads(saved[0]) if saved else {}
            # Uma alternativa mais antiga não substitui uma consulta direta mais recente.
            old_time = pd.to_datetime(previous.get("source_updated"), utc=True, errors="coerce")
            new_time = pd.to_datetime(result["source_updated"], utc=True, errors="coerce")
            if pd.isna(old_time) or new_time >= old_time:
                connection.execute(
                    "INSERT OR REPLACE INTO sync_state VALUES ('injury_snapshot',?)", (json.dumps(result),)
                )
        connection.execute(
            "INSERT OR REPLACE INTO sync_state VALUES ('injury_attempt',?)", (json.dumps(attempt),)
        )
    return attempt


def start_injury_sync(db_path: str | Path, stop_event: threading.Event) -> None:
    key = str(Path(db_path).resolve())
    with _lock:
        previous = _workers.get(key)
        if previous and previous[0].is_alive() and not previous[1].is_set():
            return

        def watch():
            while not stop_event.is_set():
                try:
                    refresh_injuries(db_path)
                except Exception:
                    import logging

                    logging.getLogger(__name__).exception("Falha no monitor de lesões")
                stop_event.wait(INTERVAL)

        thread = threading.Thread(target=watch, name="nba-injuries", daemon=True)
        _workers[key] = thread, stop_event
        thread.start()
