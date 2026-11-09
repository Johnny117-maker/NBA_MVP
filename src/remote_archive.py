"""Arquivo diário no GitHub: JSON com hash, publicação atômica e importação idempotente."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import tomllib
from pathlib import Path
from urllib.parse import quote

import requests

from .analysis_archive import archive_snapshot
from .app_paths import secrets_path
from .deploy_mode import is_cloud
from .live_store import get_state, set_state
from .live_types import utc_now

logger = logging.getLogger(__name__)

REPOSITORY = "Johnny117-maker/NBA_MVP"  # repositório oficial; é também o padrão do arquivo diário
REPOSITORY_ENV = "NBA_ARCHIVE_REPOSITORY"
BRANCH = "codex/daily-archive"
INDEX = "archive/index.json"
SEED_TAG = "prediction-seed-v1"
_lock = threading.Lock()
_workers: dict[str, tuple[threading.Thread, threading.Event]] = {}


class ArchiveError(RuntimeError):
    pass


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def archive_repository() -> str:
    """Repositório (`dono/nome`) do arquivo diário.

    Ordem: variável de ambiente NBA_ARCHIVE_REPOSITORY, `[archive].repository` em
    secrets.toml e, por fim, o repositório oficial. Valores inválidos são ignorados
    para o app nunca ficar sem repositório por um erro de digitação.
    """
    candidates = [os.environ.get(REPOSITORY_ENV, "")]
    path = secrets_path()
    if path.exists():
        try:
            with path.open("rb") as stream:
                candidates.append(str(tomllib.load(stream).get("archive", {}).get("repository", "")))
        except (OSError, tomllib.TOMLDecodeError):
            logger.warning("Não foi possível ler %s; usando o repositório padrão.", path, exc_info=True)
    for value in candidates:
        value = value.strip()
        if re.fullmatch(r"[\w.-]+/[\w.-]+", value):
            return value
    return REPOSITORY


def archive_token() -> str:
    if is_cloud():
        return ""  # a versão online nunca recebe nem usa tokens
    token = (
        os.environ.get("NBA_GITHUB_ARCHIVE_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    if token:
        return token.strip()
    path = secrets_path()
    if path.exists():
        with path.open("rb") as stream:
            token = str(tomllib.load(stream).get("archive", {}).get("github_token", "")).strip()
        if token:
            return token
    # Opcional: aproveita a autenticação local existente, sem distribuí-la no exe.
    if executable := shutil.which("gh"):
        try:
            options: dict = (
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
            )
            result = subprocess.run(
                [executable, "auth", "token", "--hostname", "github.com"],
                capture_output=True,
                text=True,
                timeout=10,
                **options,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ""


class GitHubArchive:
    def __init__(self, token: str | None = None, repository: str | None = None, branch: str = BRANCH):
        repository = repository or archive_repository()
        if (
            not re.fullmatch(r"[\w.-]+/[\w.-]+", repository)
            or not re.fullmatch(r"[\w./-]+", branch)
            or ".." in branch
        ):
            raise ValueError("Repositório ou branch inválidos.")
        self.repository, self.branch = repository, branch
        self.token = archive_token() if token is None else token

    def request(self, method: str, endpoint: str, *, body=None, missing=False, params=None):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "NBA-Analytics-Lab"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            response = requests.request(
                method,
                "https://api.github.com/repos/" + self.repository + endpoint,
                headers=headers,
                json=body,
                params=params,
                timeout=(5, 30),
            )
        except requests.RequestException:
            raise ArchiveError("GitHub indisponível; o histórico local foi preservado.") from None
        if response.status_code == 404 and missing:
            return None
        if not response.ok:
            raise ArchiveError(f"GitHub HTTP {response.status_code}. Confira acesso ao repositório privado.")
        if len(response.content) > 8_000_000:
            raise ArchiveError("Resposta do arquivo remoto excede o limite local.")
        return response.json()

    def read_json(self, path: str, *, ref: str | None = None, missing=False):
        if not re.fullmatch(r"archive/[a-zA-Z0-9_./-]+\.json", path) or ".." in path:
            raise ArchiveError("Caminho inválido no arquivo remoto.")
        result = self.request("GET", "/contents/" + path, params={"ref": ref or self.branch}, missing=missing)
        if result is None:
            return None
        if not isinstance(result, dict) or result.get("encoding") != "base64":
            raise ArchiveError("Formato inesperado no arquivo do GitHub.")
        try:
            return json.loads(base64.b64decode(result["content"], validate=False))
        except (ValueError, KeyError):
            raise ArchiveError("Arquivo remoto inválido; nenhum registro foi importado.") from None


def envelope(snapshot: dict) -> dict:
    body = {key: value for key, value in snapshot.items() if key not in {"id", "sha256", "origin"}}
    return {"payload": body, "sha256": digest(body)}


def import_envelope(db_path: str | Path, document: dict) -> bool:
    if not isinstance(document, dict):
        raise ArchiveError("Arquivo de previsão deve ser um objeto JSON.")
    body = document.get("payload")
    if not isinstance(body, dict) or digest(body) != document.get("sha256"):
        raise ArchiveError("Hash de previsão remota inválido.")
    return archive_snapshot(db_path, body, remote=True)


def publish_day(client: GitHubArchive, day: str, snapshots: list[dict], report: dict) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Data inválida.")
    ref = "/git/ref/heads/" + quote(client.branch, safe="/")
    head = client.request("GET", ref, missing=True)
    revision = head["object"]["sha"] if head else None
    commit = client.request("GET", "/git/commits/" + revision) if revision else None
    index = client.read_json(INDEX, ref=revision, missing=True) if revision else None
    index = index or {"schema_version": 1, "days": {}}
    manifest_path = f"archive/days/{day}/manifest.json"
    previous = client.read_json(manifest_path, ref=revision, missing=True) if revision else None
    files = {row["game_key"]: row for row in (previous or {}).get("files", [])}
    entries = []
    for snapshot in snapshots:
        if snapshot["day"] != day:
            raise ValueError("Previsão de outra data no lote.")
        if snapshot["game_key"] in files:
            continue  # A primeira captura permanece imutável também no GitHub.
        document = envelope(snapshot)
        home, away = snapshot["home"], snapshot["away"]
        if not re.fullmatch(r"[A-Z]{2,3}", home) or not re.fullmatch(r"[A-Z]{2,3}", away):
            raise ValueError("Equipe inválida na previsão.")
        path = f"archive/days/{day}/{away}_at_{home}.json"
        entries.append({"path": path, "mode": "100644", "type": "blob", "content": canonical(document)})
        files[snapshot["game_key"]] = dict(
            game_key=snapshot["game_key"],
            path=path,
            sha256=document["sha256"],
            captured_at=snapshot["captured_at"],
            players=len(snapshot["players"]),
        )
    manifest = {
        "schema_version": 1,
        "day": day,
        "checked_at": utc_now().isoformat(),
        "files": sorted(files.values(), key=lambda row: row["game_key"]),
        "report": report,
    }
    index["days"][day] = dict(
        path=manifest_path,
        sha256=digest(manifest),
        games=len(files),
        players=sum(row["players"] for row in files.values()),
    )
    entries.extend(
        [
            {"path": manifest_path, "mode": "100644", "type": "blob", "content": canonical(manifest)},
            {"path": INDEX, "mode": "100644", "type": "blob", "content": canonical(index)},
        ]
    )
    tree_body: dict = {"tree": entries}
    if commit:
        tree_body["base_tree"] = commit["tree"]["sha"]
    tree = client.request("POST", "/git/trees", body=tree_body)
    created = client.request(
        "POST",
        "/git/commits",
        body={
            "message": f"archive: palpites pre-jogo {day}",
            "tree": tree["sha"],
            "parents": [revision] if revision else [],
        },
    )
    if revision:
        client.request(
            "PATCH", "/git/refs/heads/" + client.branch, body={"sha": created["sha"], "force": False}
        )
    else:
        client.request(
            "POST", "/git/refs", body={"ref": "refs/heads/" + client.branch, "sha": created["sha"]}
        )
    return dict(games=len(files), commit=created["sha"], branch=client.branch)


def sync_remote_archive(db_path: str | Path, *, client=None, day: str | None = None, max_files=60) -> dict:
    client = client or GitHubArchive()
    head = client.request("GET", "/git/ref/heads/" + client.branch, missing=True)
    if head is None:
        raise ArchiveError("Arquivo remoto ainda não disponível ou sem acesso ao repositório privado.")
    revision = head["object"]["sha"]
    index = client.read_json(INDEX, ref=revision, missing=True)
    if index is None:
        raise ArchiveError("Arquivo remoto ainda não disponível ou sem acesso ao repositório privado.")
    if not isinstance(index, dict) or not isinstance(index.get("days"), dict):
        raise ArchiveError("Índice remoto inválido.")
    imported, inspected = 0, 0
    state = get_state(db_path, "remote_archive_cache", {"files": {}, "manifests": {}})
    for selected, item in sorted(index["days"].items(), reverse=True):
        if day and selected != day:
            continue
        if state["manifests"].get(selected) == item["sha256"]:
            continue
        manifest = client.read_json(item["path"], ref=revision)
        if digest(manifest) != item["sha256"]:
            raise ArchiveError("Manifesto remoto não corresponde ao hash publicado.")
        learning = manifest.get("report", {}).get("learning")
        if learning:
            known = get_state(db_path, "remote_learning_status", {})
            if learning.get("before_day", "") >= known.get("before_day", ""):
                set_state(db_path, "remote_learning_status", learning)
        completed = True
        for entry in manifest["files"]:
            if state["files"].get(entry["path"]) == entry["sha256"]:
                continue
            if inspected >= max_files:
                completed = False
                break
            document = client.read_json(entry["path"], ref=revision)
            if document.get("sha256") != entry["sha256"]:
                raise ArchiveError("Hash divergente entre manifesto e previsão.")
            imported += int(import_envelope(db_path, document))
            state["files"][entry["path"]] = entry["sha256"]
            inspected += 1
        if completed:
            state["manifests"][selected] = item["sha256"]
        set_state(db_path, "remote_archive_cache", state)
        if not completed:
            break
    result = dict(
        checked_at=utc_now().isoformat(),
        imported=imported,
        inspected=inspected,
        available_days=sorted(index["days"], reverse=True),
        error=None,
    )
    from .result_archive import sync_results

    results = sync_results(db_path, client, revision, max_files=max_files)
    result["results_imported"] = results["imported"]
    set_state(db_path, "remote_archive_status", result)
    return result


def start_remote_archive_sync(db_path: str | Path, stop_event: threading.Event) -> None:
    key = str(Path(db_path).resolve())
    with _lock:
        old = _workers.get(key)
        if old and old[0].is_alive() and not old[1].is_set():
            return

        def work():
            while not stop_event.is_set():
                try:
                    sync_remote_archive(db_path)
                except Exception as error:
                    # Rede, GitHub ou arquivo ruim não podem matar a thread de sincronização.
                    logger.warning("Falha ao sincronizar o arquivo remoto", exc_info=True)
                    set_state(
                        db_path,
                        "remote_archive_status",
                        {
                            "checked_at": utc_now().isoformat(),
                            "error": str(error) if isinstance(error, ArchiveError) else type(error).__name__,
                        },
                    )
                stop_event.wait(900)

        thread = threading.Thread(target=work, name="nba-remote-archive", daemon=True)
        _workers[key] = thread, stop_event
        thread.start()
