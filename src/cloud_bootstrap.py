"""Download e atualização dos dados na versão online (somente com NBA_DEPLOY_MODE=cloud).

O pipeline de coleta publica um pacote enxuto no Release ``data-latest`` do GitHub
(``manifest.json`` + ``nba-serving.tar.gz``). Aqui o app baixa esse pacote em
streaming, confere o SHA-256 e o tamanho declarados no manifesto e só então
troca os arquivos, um a um, por renomeação atômica (arquivo temporário na mesma
pasta + ``os.replace``). Se a rede falhar e já houver dados locais, o app
continua com eles; se não houver, devolve um estado claro em vez de exceção.

O app online nunca usa token: todas as URLs são públicas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .app_paths import data_path
from .http_retry import retry_with_backoff
from .remote_archive import archive_repository

logger = logging.getLogger(__name__)

BUNDLE_TAG = "data-latest"
MANIFEST_NAME = "manifest.json"
BUNDLE_BASE_URL_ENV = "NBA_DATA_RELEASE_BASE_URL"
CHECK_INTERVAL_SECONDS = 3600
REQUEST_TIMEOUT = (10, 60)
CHUNK_SIZE = 1024 * 1024
INSTALLED_MANIFEST_NAME = ".bundle-manifest.json"
STATUS_NAME = ".bundle-status.json"
MAIN_DB_NAME = "nba.db"
_SAFE_MEMBER = re.compile(r"^[\w.-]+(/[\w.-]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_lock = threading.Lock()

STATE_CURRENT = "current"  # já estava na versão mais recente
STATE_UPDATED = "updated"  # baixou/atualizou agora
STATE_OFFLINE = "offline"  # sem rede, mas há dados locais
STATE_UNAVAILABLE = "unavailable"  # sem rede e sem dados locais


class BootstrapError(RuntimeError):
    """Falha ao obter ou instalar o pacote de dados."""


class ManifestError(BootstrapError):
    """Manifesto ausente, ilegível ou com campos inválidos."""


class ChecksumError(BootstrapError):
    """O arquivo baixado não confere com o SHA-256/tamanho do manifesto."""


@dataclass(frozen=True)
class BundleManifest:
    version: str
    generated_at: str
    asset_name: str
    asset_bytes: int
    asset_sha256: str
    files: dict[str, int]  # caminho relativo -> tamanho descompactado

    @classmethod
    def parse(cls, payload: Any) -> BundleManifest:
        try:
            asset = payload["asset"]
            files = {str(item["name"]): int(item["bytes"]) for item in payload["files"]}
            manifest = cls(
                version=str(payload["version"]),
                generated_at=str(payload["generated_at"]),
                asset_name=str(asset["name"]),
                asset_bytes=int(asset["bytes"]),
                asset_sha256=str(asset["sha256"]).lower(),
                files=files,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ManifestError(f"Manifesto inválido: {error!r}") from error
        if not manifest.version or not _SHA256.match(manifest.asset_sha256) or manifest.asset_bytes <= 0:
            raise ManifestError("Manifesto com versão, tamanho ou SHA-256 inválido.")
        if not _SAFE_MEMBER.match(manifest.asset_name) or "/" in manifest.asset_name:
            raise ManifestError("Nome de pacote inválido no manifesto.")
        if MAIN_DB_NAME not in files or any(not _SAFE_MEMBER.match(name) or ".." in name for name in files):
            raise ManifestError("O manifesto precisa listar nba.db e apenas caminhos relativos seguros.")
        return manifest


@dataclass(frozen=True)
class BundleStatus:
    state: str
    version: str = ""
    generated_at: str = ""
    checked_at: str = ""
    error: str = ""

    @property
    def has_data(self) -> bool:
        return self.state != STATE_UNAVAILABLE


def data_dir() -> Path:
    return data_path(MAIN_DB_NAME).parent


def release_base_url() -> str:
    override = os.environ.get(BUNDLE_BASE_URL_ENV, "").strip().rstrip("/")
    if override:
        return override
    return f"https://github.com/{archive_repository()}/releases/download/{BUNDLE_TAG}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_installed_manifest(directory: Path | None = None) -> BundleManifest | None:
    path = (directory or data_dir()) / INSTALLED_MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return BundleManifest.parse(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, BootstrapError):
        logger.warning("Manifesto instalado ilegível em %s; será baixado de novo.", path, exc_info=True)
        return None


def read_status(directory: Path | None = None) -> BundleStatus | None:
    """Último estado gravado (para a página Sistema), ou ``None`` se nunca houve checagem."""
    path = (directory or data_dir()) / STATUS_NAME
    try:
        return BundleStatus(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _manifest_payload(manifest: BundleManifest) -> dict[str, Any]:
    return {
        "version": manifest.version,
        "generated_at": manifest.generated_at,
        "asset": {
            "name": manifest.asset_name,
            "bytes": manifest.asset_bytes,
            "sha256": manifest.asset_sha256,
        },
        "files": [{"name": name, "bytes": size} for name, size in manifest.files.items()],
    }


def _get(session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    from .http_retry import TRANSIENT_STATUS, TransientHTTPError

    def attempt() -> requests.Response:
        response = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
        if response.status_code in TRANSIENT_STATUS:
            response.close()
            raise TransientHTTPError(response)
        return response

    return retry_with_backoff(attempt, attempts=3, label=f"download {url.rsplit('/', 1)[-1]}")


def fetch_manifest(session: requests.Session, base_url: str | None = None) -> BundleManifest:
    url = f"{base_url or release_base_url()}/{MANIFEST_NAME}"
    try:
        response = _get(session, url)
    except requests.RequestException as error:
        raise BootstrapError(f"Não foi possível consultar {MANIFEST_NAME}: {error}") from error
    with response:
        if response.status_code == 404:
            raise ManifestError("Pacote de dados ainda não publicado (manifest.json ausente no Release).")
        if response.status_code != 200:
            raise BootstrapError(f"Consulta ao manifesto retornou HTTP {response.status_code}.")
        try:
            payload = json.loads(response.text)
        except ValueError as error:
            raise ManifestError("manifest.json não é um JSON válido.") from error
    return BundleManifest.parse(payload)


def download_asset(
    session: requests.Session, manifest: BundleManifest, target: Path, base_url: str | None = None
) -> None:
    """Baixa o pacote em streaming para ``target`` (arquivo temporário), conferindo SHA-256 e tamanho.

    Em qualquer falha (rede interrompida, tamanho ou hash diferentes) o arquivo parcial é apagado.
    """
    url = f"{base_url or release_base_url()}/{manifest.asset_name}"
    try:
        response = _get(session, url, stream=True)
    except requests.RequestException as error:
        raise BootstrapError(f"Não foi possível baixar {manifest.asset_name}: {error}") from error
    digest = hashlib.sha256()
    received = 0
    try:
        with response, target.open("wb") as output:
            if response.status_code != 200:
                raise BootstrapError(
                    f"Download de {manifest.asset_name} retornou HTTP {response.status_code}."
                )
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                digest.update(chunk)
                received += len(chunk)
                if received > manifest.asset_bytes:
                    raise ChecksumError("O download passou do tamanho declarado no manifesto.")
                output.write(chunk)
    except requests.RequestException as error:
        target.unlink(missing_ok=True)
        raise BootstrapError(f"Download de {manifest.asset_name} interrompido: {error}") from error
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if received != manifest.asset_bytes or digest.hexdigest() != manifest.asset_sha256:
        target.unlink(missing_ok=True)
        raise ChecksumError(
            f"{manifest.asset_name} não confere com o manifesto (tamanho ou SHA-256 diferentes)."
        )


def extract_bundle(archive: Path, staging: Path, manifest: BundleManifest) -> None:
    """Extrai só os arquivos listados no manifesto, rejeitando caminhos perigosos e tamanhos errados."""
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            names = {member.name for member in members if member.isfile()}
            for member in members:
                if member.isdir():
                    continue
                if not member.isfile() or not _SAFE_MEMBER.match(member.name) or ".." in member.name:
                    raise BootstrapError(f"Entrada inválida no pacote: {member.name!r}")
                if member.name not in manifest.files or member.size != manifest.files[member.name]:
                    raise ChecksumError(f"Arquivo inesperado ou com tamanho diferente: {member.name!r}")
                destination = staging / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise BootstrapError(f"Não foi possível ler {member.name!r} do pacote.")
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except (tarfile.TarError, EOFError, OSError) as error:
        raise BootstrapError(f"Pacote de dados corrompido: {error}") from error
    missing = set(manifest.files) - names
    if missing:
        raise ChecksumError(f"Arquivos ausentes no pacote: {sorted(missing)}")


def install_staged(staging: Path, directory: Path, manifest: BundleManifest) -> None:
    """Move cada arquivo para o lugar definitivo por renomeação atômica; ``nba.db`` por último."""
    directory.mkdir(parents=True, exist_ok=True)
    ordered = sorted(manifest.files, key=lambda name: (name == MAIN_DB_NAME, name))
    for name in ordered:
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("-wal", "-shm"):  # resíduos de um banco antigo não podem acompanhar o novo
            destination.with_name(destination.name + suffix).unlink(missing_ok=True)
        os.replace(staging / name, destination)
    _write_json_atomic(directory / INSTALLED_MANIFEST_NAME, _manifest_payload(manifest))


def _save_status(directory: Path, status: BundleStatus) -> None:
    try:
        _write_json_atomic(directory / STATUS_NAME, asdict(status))
    except OSError:
        logger.warning("Não foi possível gravar o estado do pacote de dados.", exc_info=True)


def has_local_data(directory: Path | None = None) -> bool:
    return ((directory or data_dir()) / MAIN_DB_NAME).exists()


def sync_bundle(
    session: requests.Session | None = None,
    directory: Path | None = None,
    base_url: str | None = None,
    now: Callable[[], str] = _now,
) -> BundleStatus:
    """Garante os dados locais: baixa se faltam ou se há versão mais nova; nunca lança por falha de rede."""
    target = directory or data_dir()
    own_session = session is None
    client = session or requests.Session()
    installed = read_installed_manifest(target)
    local = has_local_data(target)
    try:
        with _lock:
            try:
                manifest = fetch_manifest(client, base_url)
                if local and installed is not None and installed.asset_sha256 == manifest.asset_sha256:
                    status = BundleStatus(STATE_CURRENT, manifest.version, manifest.generated_at, now())
                else:
                    status = _download_and_install(client, manifest, target, base_url, now)
            except BootstrapError as error:
                logger.warning("Atualização dos dados falhou: %s", error, exc_info=True)
                version = installed.version if installed and local else ""
                generated = installed.generated_at if installed and local else ""
                state = STATE_OFFLINE if local else STATE_UNAVAILABLE
                status = BundleStatus(state, version, generated, now(), str(error))
    finally:
        if own_session:
            client.close()
    if target.exists() or status.has_data:
        _save_status(target, status)
    return status


def _download_and_install(
    client: requests.Session,
    manifest: BundleManifest,
    directory: Path,
    base_url: str | None,
    now: Callable[[], str],
) -> BundleStatus:
    directory.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".download-", dir=directory))
    try:
        archive = work / manifest.asset_name
        download_asset(client, manifest, archive, base_url)
        staging = work / "staging"
        extract_bundle(archive, staging, manifest)
        install_staged(staging, directory, manifest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    logger.info("Dados atualizados para a versão %s.", manifest.version)
    return BundleStatus(STATE_UPDATED, manifest.version, manifest.generated_at, now())
