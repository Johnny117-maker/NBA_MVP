"""Gera o pacote enxuto de dados que a versão online baixa (``nba-serving-<versão>.tar.gz``).

Regras de corte, todas verificadas no código das páginas:

* ``player_shots`` **não** é resumido em agregados: a página Mapa de Arremessos lê as linhas
  brutas (``SELECT *``) de cada jogador. Só existe corte opcional por temporada
  (``min_shot_season``), desligado por padrão.
* Tabelas operacionais do monitor (``http_cache``, ``api_usage``, ``sync_lease``) só são
  usadas por ações desabilitadas na nuvem; vão vazias.
* Arquivos parquet de ``history/`` são lidos por Defesa/Marcações/Lesões; entram quando
  existem. Se forem excluídos, as linhas correspondentes de ``assets`` saem junto, para a
  página dizer "não coletado" em vez de falhar por arquivo ausente.
* Todos os bancos auxiliares são criados com o esquema completo (mesmo vazios), pois a
  nuvem abre tudo em somente leitura e um arquivo ausente seria um erro.
* Bancos em ``journal_mode=DELETE`` e ``VACUUM`` (sem ``-wal``/``-shm`` ao lado).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis_archive import archive_path, connect_archive
from .history_store import connect_history, history_path, history_root
from .live_store import connect_state, state_path
from .shot_storage import init_shots_db
from .store.schema import init_db

logger = logging.getLogger(__name__)

TARGET_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
TARGET_COMPRESSED_BYTES = 100 * 1024 * 1024
GITHUB_ASSET_LIMIT_BYTES = 2 * 1024**3 - 1
OPERATIONAL_TABLES = ("http_cache", "api_usage", "sync_lease")

_INGESTION_PROVENANCE = (
    "CREATE TABLE IF NOT EXISTS ingestion_provenance "
    "(game_id TEXT PRIMARY KEY, source TEXT, fingerprint TEXT, updated_at TEXT)"
)


class BundleBuildError(RuntimeError):
    """O pacote não pôde ser gerado com segurança."""


def _backup(source: Path, target: Path) -> None:
    """Cópia consistente de um SQLite (API de backup), mesmo com o banco em uso."""
    target.parent.mkdir(parents=True, exist_ok=True)
    origin = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        origin.backup(destination)
    finally:
        destination.close()
        origin.close()


def ensure_all_schemas(db_path: Path) -> None:
    """Cria (se faltar) o esquema de todos os bancos que as páginas abrem."""
    init_db(db_path)
    init_shots_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(_INGESTION_PROVENANCE)
        connection.commit()
    finally:
        connection.close()
    for connect in (connect_state, connect_archive, connect_history):
        connect(db_path).close()


def _finalize_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("VACUUM")
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _prune(work_db: Path, min_shot_season: str | None, include_history: bool) -> list[str]:
    """Aplica os cortes no banco de trabalho; devolve os parquet que entram no pacote."""
    root = history_root(work_db)
    keep: list[str] = []
    state = sqlite3.connect(state_path(work_db))
    try:
        for table in OPERATIONAL_TABLES:
            state.execute(f"DELETE FROM {table}")
        state.commit()
    finally:
        state.close()
    if min_shot_season:
        main = sqlite3.connect(work_db)
        try:
            main.execute("DELETE FROM player_shots WHERE season < ?", (min_shot_season,))
            main.commit()
        finally:
            main.close()
    history = sqlite3.connect(history_path(work_db))
    try:
        for tag, name, relative in history.execute("SELECT tag, name, relative_path FROM assets").fetchall():
            present = bool(relative) and (root / relative).is_file()
            if include_history and present:
                keep.append(f"history/{relative}")
            else:
                history.execute("DELETE FROM assets WHERE tag=? AND name=?", (tag, name))
        history.commit()
    finally:
        history.close()
    return sorted(set(keep))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_archive(files: dict[str, Path], target: Path) -> None:
    """tar.gz com ordem e carimbo de tempo fixos (mesma entrada → mesmo arquivo)."""
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                for name in sorted(files):
                    info = bundle.gettarinfo(str(files[name]), arcname=name)
                    info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                    info.mode = 0o644
                    with files[name].open("rb") as stream:
                        bundle.addfile(info, stream)


def build_serving_bundle(
    source_db: Path,
    output_dir: Path,
    *,
    version: str | None = None,
    min_shot_season: str | None = None,
    include_history: bool = True,
) -> dict[str, Any]:
    """Gera ``nba-serving-<versão>.tar.gz`` e ``manifest.json`` em ``output_dir``.

    Nunca altera os bancos de origem (trabalha sobre cópias). Devolve o manifesto com os
    tamanhos reais, mais ``report`` (não publicado) com a comparação com as metas.
    """
    source_db = Path(source_db)
    if not source_db.exists():
        raise BundleBuildError(f"Banco de origem não encontrado: {source_db}")
    stamp = datetime.now(UTC)
    version = version or stamp.strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nba-bundle-") as temp:
        work = Path(temp) / "data" / "nba.db"
        _backup(source_db, work)
        for origin, target in (
            (state_path(source_db), state_path(work)),
            (archive_path(source_db), archive_path(work)),
            (history_path(source_db), history_path(work)),
        ):
            if origin.exists():
                _backup(origin, target)
        if history_root(source_db).is_dir():
            shutil.copytree(history_root(source_db), history_root(work), dirs_exist_ok=True)
        ensure_all_schemas(work)
        parquet = _prune(work, min_shot_season, include_history)
        databases = [work, state_path(work), archive_path(work), history_path(work)]
        for database in databases:
            _finalize_sqlite(database)
        files: dict[str, Path] = {database.name: database for database in databases}
        files.update({relative: work.parent / relative for relative in parquet})
        missing = [name for name, path in files.items() if not path.is_file()]
        if missing:
            raise BundleBuildError(f"Arquivos esperados ausentes: {missing}")
        asset_name = f"nba-serving-{version}.tar.gz"
        archive = output_dir / asset_name
        _write_archive(files, archive)
        sizes = {name: path.stat().st_size for name, path in files.items()}
    uncompressed = sum(sizes.values())
    compressed = archive.stat().st_size
    if compressed > GITHUB_ASSET_LIMIT_BYTES:
        archive.unlink(missing_ok=True)
        raise BundleBuildError("O pacote excede o limite de 2 GiB por arquivo do Release.")
    manifest: dict[str, Any] = {
        "version": version,
        "generated_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asset": {"name": asset_name, "bytes": compressed, "sha256": _sha256(archive)},
        "files": [{"name": name, "bytes": size} for name, size in sorted(sizes.items())],
        "uncompressed_bytes": uncompressed,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Pacote %s: %d B compactado, %d B descompactado.", asset_name, compressed, uncompressed)
    return manifest


def size_report(manifest: dict[str, Any]) -> str:
    """Tamanhos reais do pacote frente às metas (sem estimativas)."""
    uncompressed = int(manifest["uncompressed_bytes"])
    compressed = int(manifest["asset"]["bytes"])
    mib = 1024 * 1024

    def verdict(value: int, target: int) -> str:
        return "dentro da meta" if value <= target else "ACIMA da meta"

    lines = [
        f"Descompactado: {uncompressed / mib:.2f} MiB (meta ≤ {TARGET_UNCOMPRESSED_BYTES // mib} MiB: "
        f"{verdict(uncompressed, TARGET_UNCOMPRESSED_BYTES)})",
        f"Compactado:    {compressed / mib:.2f} MiB (meta ≤ {TARGET_COMPRESSED_BYTES // mib} MiB: "
        f"{verdict(compressed, TARGET_COMPRESSED_BYTES)})",
    ]
    for item in sorted(manifest["files"], key=lambda entry: -int(entry["bytes"]))[:8]:
        lines.append(f"  {item['name']}: {int(item['bytes']) / mib:.2f} MiB")
    return "\n".join(lines)


def pack_full_data(source_db: Path, output: Path) -> str:
    """Empacota a base completa (todos os bancos e ``history/``) e devolve o SHA-256.

    Serve de ponto de partida para o próximo ciclo do ``data-refresh``; nunca vai para o app.
    """
    source_db = Path(source_db)
    if not source_db.exists():
        raise BundleBuildError(f"Banco de origem não encontrado: {source_db}")
    with tempfile.TemporaryDirectory(prefix="nba-full-") as temp:
        work = Path(temp) / "data" / "nba.db"
        _backup(source_db, work)
        for origin, target in (
            (state_path(source_db), state_path(work)),
            (archive_path(source_db), archive_path(work)),
            (history_path(source_db), history_path(work)),
        ):
            if origin.exists():
                _backup(origin, target)
        if history_root(source_db).is_dir():
            shutil.copytree(history_root(source_db), history_root(work), dirs_exist_ok=True)
        files = {
            str(path.relative_to(work.parent)): path for path in work.parent.rglob("*") if path.is_file()
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_archive(files, output)
    if output.stat().st_size > GITHUB_ASSET_LIMIT_BYTES:
        output.unlink(missing_ok=True)
        raise BundleBuildError("A base completa excede o limite de 2 GiB por arquivo do Release.")
    return _sha256(output)
