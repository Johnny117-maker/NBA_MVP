"""Downloads retomáveis de arquivos públicos NBA/ESPN, com procedência e integridade."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import requests

from .history_store import connect_history, history_root, set_history_state
from .http_retry import TRANSIENT_STATUS, TransientHTTPError, retry_with_backoff
from .live_types import current_season, utc_now
from .source_health import record_source_result

logger = logging.getLogger(__name__)

HISTORY_SOURCE = "Acervo histórico (GitHub)"

BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
CATALOG_URL = "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases"
TAGS = {
    "espn_nba_injuries",
    "nba_stats_schedules",
    "nba_stats_team_boxscores",
    "nba_stats_player_boxscores",
    "nba_stats_shots",
    "nba_stats_pbp",
    "nba_stats_possessions",
    "nba_stats_leaguedash",
    "nba_stats_rosters",
    "nba_stats_lineups",
    "nba_stats_team_season_stats",
    "nba_stats_player_season_stats",
    "nba_stats_game_rosters",
    "nba_stats_game_lineups",
    "nba_stats_hustle",
    "nba_stats_matchups",
    "nba_stats_game_matchups",
    "nba_stats_synergy",
    "nba_stats_officials",
    "nba_stats_standings",
    "nba_crosswalk",
    "espn_nba_schedules",
    "espn_nba_player_boxscores",
    "espn_nba_team_boxscores",
    "espn_nba_shots",
    "espn_nba_rosters",
    "espn_nba_player_season_stats",
    "espn_nba_team_season_stats",
    "espn_nba_game_rosters",
}
CORE = {
    "espn_nba_team_boxscores",
    "nba_stats_schedules",
    "nba_stats_shots",
    "nba_stats_pbp",
    "nba_stats_game_matchups",
}


@dataclass(frozen=True)
class PublicAsset:
    tag: str
    name: str
    year: int
    source_url: str
    updated_at: str
    size: int


def select_assets(
    releases: list[dict], start_year: int, end_year: int, *, core: bool = False
) -> list[PublicAsset]:
    result = {}
    for release in releases:
        tag = release.get("tag_name", release.get("tag", ""))
        if tag not in TAGS:
            continue
        for file in release.get("assets", release.get("files", [])):
            name = file.get("name", "")
            match = re.fullmatch(r"[a-zA-Z0-9_-]+_(\d{4})\.parquet", name)
            if not match or not start_year <= int(match[1]) <= end_year:
                continue
            if (
                core
                and tag not in CORE
                and not (tag == "nba_stats_leaguedash" and name.startswith("team_master_"))
            ):
                continue
            url = file.get("browser_download_url", file.get("url", ""))
            if url != f"{BASE}/{tag}/{name}" or not 0 < int(file.get("size", 0)) <= 150_000_000:
                continue
            asset = PublicAsset(tag, name, int(match[1]), url, file.get("updated_at", ""), int(file["size"]))
            result[tag, name] = asset
    return sorted(result.values(), key=lambda asset: (-asset.year, asset.tag, asset.name))


def discover_releases(db_path: str | Path, *, refresh: bool = False) -> list[dict]:
    root = history_root(db_path)
    root.mkdir(parents=True, exist_ok=True)
    cached = root / "catalog.json"
    if not refresh and cached.exists() and utc_now().timestamp() - cached.stat().st_mtime < 3600:
        return json.loads(cached.read_text(encoding="utf-8"))
    releases: list[dict] = []
    for page in range(1, 9):
        def fetch_page(page: int = page) -> requests.Response:
            reply = requests.get(CATALOG_URL, params={"per_page": 100, "page": page}, timeout=(5, 30))
            if reply.status_code in TRANSIENT_STATUS:
                raise TransientHTTPError(reply)
            return reply

        try:
            try:
                response = retry_with_backoff(
                    fetch_page, attempts=3, base_delay=2.0, label="Catálogo do acervo"
                )
            except TransientHTTPError as error:
                response = error.reply
            response.raise_for_status()
            batch = response.json()
        except (requests.RequestException, ValueError) as error:
            record_source_result(db_path, HISTORY_SOURCE, type(error).__name__)
            raise
        record_source_result(db_path, HISTORY_SOURCE)
        if not isinstance(batch, list):
            raise ValueError("Catálogo público retornou um formato inesperado.")
        releases.extend(row for row in batch if row.get("tag_name") in TAGS)
        if len(batch) < 100:
            break
    cached.write_text(json.dumps(releases), encoding="utf-8")
    return releases


def download_asset(db_path: str | Path, asset: PublicAsset) -> dict:
    relative = f"{asset.tag}/{asset.name}"
    target = history_root(db_path) / relative
    with connect_history(db_path) as connection:
        previous = connection.execute(
            "SELECT source_updated,sha256,bytes FROM assets WHERE tag=? AND name=?", (asset.tag, asset.name)
        ).fetchone()
    if (
        previous
        and previous[0] == asset.updated_at
        and target.is_file()
        and target.stat().st_size == previous[2]
    ):
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == previous[1]:
                return {"status": "cached", "tag": asset.tag, "name": asset.name}
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        def stream_asset() -> tuple[Any, int]:
            """Baixa o arquivo inteiro; uma queda no meio recomeça do zero na próxima tentativa."""
            hasher, total = hashlib.sha256(), 0
            with requests.get(asset.source_url, timeout=(5, 40), stream=True) as response:
                if response.status_code in TRANSIENT_STATUS:
                    raise TransientHTTPError(response)
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        total += len(chunk)
                        if total > 150_000_000:
                            raise ValueError("Arquivo excede o limite de 150 MB por conjunto.")
                        hasher.update(chunk)
                        output.write(chunk)
            return hasher, total

        try:
            digest, size = retry_with_backoff(stream_asset, attempts=3, base_delay=2.0, label=asset.name)
        except TransientHTTPError as error:
            error.reply.raise_for_status()
            raise
        if size != asset.size:
            raise ValueError("Tamanho do download diverge do catálogo público.")
        metadata = pq.ParquetFile(temporary).metadata
        # Só substitui a versão anterior após validar tamanho e formato.
        temporary.replace(target)
        with connect_history(db_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    asset.tag,
                    asset.name,
                    asset.year,
                    asset.source_url,
                    asset.updated_at,
                    utc_now().isoformat(),
                    digest.hexdigest(),
                    size,
                    metadata.num_rows,
                    metadata.num_columns,
                    relative,
                ),
            )
        return {"status": "downloaded", "tag": asset.tag, "name": asset.name, "rows": metadata.num_rows}
    finally:
        temporary.unlink(missing_ok=True)


def collect_history(
    db_path: str | Path,
    *,
    start_year: int = 2022,
    end_year: int | None = None,
    core: bool = False,
    releases: list[dict] | None = None,
    progress=None,
) -> dict:
    end_year = end_year or int(current_season()[:4]) + 1
    if not 2002 <= start_year <= end_year <= int(current_season()[:4]) + 1:
        raise ValueError("Intervalo de temporadas inválido.")
    releases = releases if releases is not None else discover_releases(db_path)
    assets = select_assets(releases, start_year, end_year, core=core)
    if not assets:
        raise ValueError("Nenhum arquivo público disponível para o intervalo solicitado.")
    result: dict = {
        "started_at": utc_now().isoformat(),
        "planned": len(assets),
        "downloaded": 0,
        "cached": 0,
        "errors": [],
    }
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="nba-history") as pool:
        futures = {pool.submit(download_asset, db_path, asset): asset for asset in assets}
        for index, future in enumerate(as_completed(futures), 1):
            asset = futures[future]
            try:
                item = future.result()
                result[item["status"]] += 1
            except Exception as error:
                # Um arquivo com erro (rede, zip, parse) não interrompe os demais downloads.
                logger.warning("Falha ao baixar o arquivo %s", asset.name, exc_info=True)
                result["errors"].append({"tag": asset.tag, "name": asset.name, "error": type(error).__name__})
            if progress:
                progress(index, len(assets), asset.name)
    from .history_normalize import normalize_history

    result["normalized"] = normalize_history(db_path, years=set(range(start_year, end_year + 1)))
    result["completed_at"] = utc_now().isoformat()
    set_history_state(db_path, "last_sync", result)
    return result


_workers: dict[str, tuple[threading.Thread, threading.Event]] = {}
_worker_lock = threading.Lock()


def start_current_history_sync(db_path: str | Path, stop_event: threading.Event) -> None:
    """Uma tarefa diária independente; downloads não interrompem a consulta dos jogos ao vivo."""
    key = str(Path(db_path).resolve())
    with _worker_lock:
        if key in _workers and _workers[key][0].is_alive() and not _workers[key][1].is_set():
            return

        def work() -> None:
            from .history_store import get_history_state

            while not stop_event.is_set():
                previous = get_history_state(db_path, "daily_sync", {})
                moment = utc_now()
                last = previous.get("attempted_at")
                if not last or (moment - datetime.fromisoformat(last)).total_seconds() >= 6 * 3600:
                    try:
                        year = int(current_season()[:4]) + 1
                        result = collect_history(db_path, start_year=year, end_year=year, core=True)
                        from .player_matchups import collect_pending_matchups

                        result["direct_matchups"] = collect_pending_matchups(db_path)
                        state = {
                            "attempted_at": moment.isoformat(),
                            "errors": len(result["errors"]) + len(result["normalized"].get("errors", [])),
                        }
                    except Exception as error:
                        # O monitor em segundo plano continua vivo após qualquer falha da fonte.
                        logger.warning("Falha na sincronização diária de defesa", exc_info=True)
                        state = {"attempted_at": moment.isoformat(), "error": type(error).__name__}
                    set_history_state(db_path, "daily_sync", state)
                stop_event.wait(60)

        thread = threading.Thread(target=work, name="nba-defense-sync", daemon=True)
        _workers[key] = (thread, stop_event)
        thread.start()
