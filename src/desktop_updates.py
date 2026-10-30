"""Atualizações paralelas ao programa em uso; dados pessoais não entram no pacote."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import requests

from .desktop_support import APP_VERSION
from .remote_archive import REPOSITORY, ArchiveError, GitHubArchive


class UpdateError(RuntimeError):
    pass


def version_tuple(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise UpdateError("Versão de atualização inválida.")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def check_update(*, current=APP_VERSION, client=None) -> dict:
    client = client or GitHubArchive()
    if client.repository != REPOSITORY:
        raise UpdateError("Repositório de atualização não autorizado.")
    release = client.request("GET", "/releases/latest")
    version = str(release.get("tag_name", "")).removeprefix("v")
    if version_tuple(version) <= version_tuple(current):
        return dict(status="no_update", current=current, latest=version)
    if release.get("draft") or release.get("prerelease"):
        raise UpdateError("Somente versões estáveis publicadas podem ser preparadas.")
    name = f"NBAAnalyticsLab-{version}-program-Windows-x64.zip"
    asset = next((a for a in release.get("assets", []) if a.get("name") == name), None)
    if not asset or asset.get("state") != "uploaded":
        raise UpdateError("O pacote de atualização desta versão ainda não está disponível.")
    digest = str(asset.get("digest", ""))
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise UpdateError("O GitHub não informou o SHA-256 do pacote.")
    size = int(asset.get("size", 0))
    if not 0 < size <= 1_500_000_000:
        raise UpdateError("Tamanho inválido do pacote de atualização.")
    return dict(
        status="available",
        current=current,
        latest=version,
        asset_id=int(asset["id"]),
        size=size,
        sha256=digest.split(":", 1)[1],
        name=name,
        url=f"https://github.com/{REPOSITORY}/releases/tag/v{version}",
    )


def extract_program(archive_path: Path, destination: Path, version: str) -> Path:
    version_tuple(version)
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > 30000 or sum(e.file_size for e in entries) > 5_000_000_000:
            raise UpdateError("Pacote excede os limites de extração.")
        seen = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.orig_filename
                or ":" in entry.filename
                or not path.parts
                or path.parts[0] != "NBAAnalyticsLab"
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise UpdateError("Caminho inseguro no pacote de atualização.")
            key = str(path).casefold()
            if key in seen:
                raise UpdateError("O pacote contém caminhos duplicados.")
            seen.add(key)
            if key.startswith("nbaanalyticslab/_internal/seed/"):
                raise UpdateError("O pacote de programa não deve substituir a base de dados.")
        if shutil.disk_usage(destination).free < sum(e.file_size for e in entries) + 100_000_000:
            raise UpdateError("Espaço insuficiente para preparar a atualização.")
        for entry in entries:
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise UpdateError("Arquivo fora da pasta de preparação.")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    program = destination / "NBAAnalyticsLab"
    try:
        manifest = json.loads((program / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UpdateError("Manifesto do programa ausente ou inválido.") from None
    if manifest.get("version") != version or not manifest.get("requires_existing_data"):
        raise UpdateError("O manifesto não corresponde à atualização solicitada.")
    if not (program / "NBAAnalyticsLab.exe").is_file() or not (program / "CRIAR_ATALHO.bat").is_file():
        raise UpdateError("O pacote não contém os arquivos de inicialização.")
    return program


def prepare_update(
    info: dict, profile: Path, *, client=None, previous_executable: Path | None = None
) -> dict:
    client = client or GitHubArchive()
    if client.repository != REPOSITORY or info.get("status") != "available":
        raise UpdateError("Atualização não foi verificada.")
    version = str(info["latest"])
    version_tuple(version)
    if not (profile / "data/nba.db").is_file():
        raise UpdateError("Este pacote requer uma instalação com base existente. Use o pacote completo.")
    updates = profile.resolve() / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    final = updates / version
    if final.exists():
        raise UpdateError("Esta versão já foi preparada. Consulte a pasta de atualizações.")
    if shutil.disk_usage(updates).free < int(info["size"]) * 3 + 300_000_000:
        raise UpdateError("Libere espaço antes de preparar a atualização.")
    with tempfile.TemporaryDirectory(prefix=".download-", dir=updates) as temporary:
        temporary_path = Path(temporary)
        download = temporary_path / "program.zip"
        count, hasher = 0, hashlib.sha256()
        headers = {"Accept": "application/octet-stream", "User-Agent": "NBA-Analytics-Lab"}
        if client.token:
            headers["Authorization"] = "Bearer " + client.token
        try:
            with requests.get(
                f"https://api.github.com/repos/{REPOSITORY}/releases/assets/{int(info['asset_id'])}",
                headers=headers,
                stream=True,
                timeout=(5, 60),
            ) as response:
                response.raise_for_status()
                with download.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        count += len(chunk)
                        if count > int(info["size"]):
                            raise UpdateError("Download excedeu o tamanho publicado.")
                        hasher.update(chunk)
                        output.write(chunk)
        except requests.RequestException:
            raise UpdateError("Não foi possível baixar a atualização do GitHub.") from None
        if count != int(info["size"]) or hasher.hexdigest() != info["sha256"]:
            raise UpdateError("O SHA-256 da atualização não confere.")
        stage = temporary_path / "stage"
        stage.mkdir()
        try:
            program = extract_program(download, stage, version)
        except zipfile.BadZipFile:
            raise UpdateError("Pacote ZIP inválido.") from None
        final.mkdir()
        program.rename(final / "NBAAnalyticsLab")
    previous = previous_executable or (Path(sys.executable) if getattr(sys, "frozen", False) else None)
    result = dict(
        version=version,
        executable=str(final / "NBAAnalyticsLab/NBAAnalyticsLab.exe"),
        previous_executable=str(previous) if previous else None,
        sha256=info["sha256"],
    )
    (updates / "last_prepared.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def activate_shortcut(executable: str) -> None:
    target = Path(executable)
    script = target.parent / "CRIAR_ATALHO.bat"
    if (
        os.name != "nt"
        or target.name != "NBAAnalyticsLab.exe"
        or not target.is_file()
        or not script.is_file()
    ):
        raise UpdateError("Não foi possível localizar a versão e seu criador de atalho.")
    options: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    result = subprocess.run(
        ["cmd", "/c", str(script), "--no-pause"],
        cwd=target.parent,
        capture_output=True,
        timeout=45,
        **options,
    )
    if result.returncode:
        raise UpdateError("O atalho não foi atualizado. Execute CRIAR_ATALHO.bat na pasta preparada.")


__all__ = ["ArchiveError", "UpdateError", "check_update", "prepare_update", "activate_shortcut"]
