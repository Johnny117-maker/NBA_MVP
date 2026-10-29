"""Inicialização portátil sem depender da pasta de onde o executável foi aberto."""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import sys
import uuid
from pathlib import Path

APP_NAME = "NBA Analytics Lab"
APP_VERSION = "1.2.0"


def resource_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_user_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "NBAAnalyticsLab"


def initialize_user_data(root: Path, resources: Path) -> None:
    """A semente só preenche arquivos ausentes; uma atualização nunca substitui a base pessoal."""
    root = root.resolve()
    for directory in ("data", "models", "reports", "logs", ".streamlit"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    files = [
        (resources / "seed" / name, root / "data" / name)
        for name in ("nba.db", "nba_sync.sqlite", "nba_schedule.json", "nba_history.sqlite")
    ]
    seed_history = resources / "seed" / "history"
    if seed_history.is_dir():
        files.extend(
            (file, root / "data" / "history" / file.relative_to(seed_history))
            for file in seed_history.rglob("*")
            if file.is_file()
        )
    files.extend(
        [
            (resources / ".streamlit" / "config.toml", root / ".streamlit" / "config.toml"),
            (resources / ".streamlit" / "secrets.example.toml", root / ".streamlit" / "secrets.example.toml"),
        ]
    )
    for source, target in files:
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            shutil.copyfile(source, temporary)
            # A trava da janela principal protege a criação inicial; o filho só abre os mesmos arquivos.
            if not target.exists():
                temporary.replace(target)
            else:
                temporary.unlink()


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def server_command(port: int, root: Path, parent_pid: int) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(resource_root() / "desktop_launcher.py"))
    return [
        *command,
        "--serve",
        "--port",
        str(port),
        "--data-dir",
        str(root),
        "--parent-pid",
        str(parent_pid),
    ]


def instance_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
