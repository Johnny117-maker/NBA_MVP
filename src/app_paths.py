"""Recursos do programa separados dos dados graváveis do usuário."""

from __future__ import annotations

import os
from pathlib import Path

from .deploy_mode import cloud_data_home, is_cloud

RESOURCE_ROOT = Path(__file__).resolve().parents[1]


def state_root() -> Path:
    configured = os.environ.get("NBA_DATA_HOME")
    if not configured and is_cloud():
        configured = cloud_data_home()
    return Path(configured).expanduser().resolve() if configured else RESOURCE_ROOT


def data_path(name: str) -> Path:
    return state_root() / "data" / name


def report_path(name: str) -> Path:
    local = state_root() / "reports" / name
    return local if local.exists() else RESOURCE_ROOT / "reports" / name


def secrets_path() -> Path:
    return state_root() / ".streamlit" / "secrets.toml"
