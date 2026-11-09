"""Modo de implantação: local (padrão) ou nuvem somente leitura.

Tudo o que é específico da versão online só vale quando ``NBA_DEPLOY_MODE=cloud``
(variável de ambiente ou Secrets do Streamlit). Sem a variável, o aplicativo —
incluindo o executável do Windows — se comporta exatamente como antes.

Este módulo não importa nada do projeto para poder ser usado por ``app_paths``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_DEPLOY_MODE = "NBA_DEPLOY_MODE"
CLOUD_VALUE = "cloud"
CLOUD_DEFAULT_DATA_HOME = "/tmp/nba-data"
READ_ONLY_NOTICE = "Somente leitura nesta versão online."

# Credenciais que nunca devem existir no app online.
_TOKEN_ENV_VARS = ("NBA_GITHUB_ARCHIVE_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")

_original_connect: Callable[..., sqlite3.Connection] = sqlite3.connect


def _secret_value(name: str) -> str:
    """Lê ``name`` dos Secrets do Streamlit, se existirem (sem exigir arquivo)."""
    try:
        import streamlit as st

        return str(st.secrets.get(name, "") or "")
    except (FileNotFoundError, KeyError, RuntimeError, AttributeError) as error:
        logger.debug("Secrets do Streamlit indisponíveis para %s: %s", name, error)
        return ""


def is_cloud() -> bool:
    """Verdadeiro apenas quando ``NBA_DEPLOY_MODE=cloud`` (ambiente ou Secrets)."""
    value = os.environ.get(ENV_DEPLOY_MODE) or _secret_value(ENV_DEPLOY_MODE)
    return value.strip().lower() == CLOUD_VALUE


def cloud_data_home() -> str:
    """Diretório gravável dos dados na nuvem (``NBA_DATA_HOME`` ou ``/tmp/nba-data``)."""
    return os.environ.get("NBA_DATA_HOME") or CLOUD_DEFAULT_DATA_HOME


def read_only_active() -> bool:
    """Verdadeiro quando o acesso ao SQLite está forçado a somente leitura."""
    return sqlite3.connect is not _original_connect and is_cloud()


def _connect_read_only(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
    if isinstance(database, (str, os.PathLike)):
        text = os.fspath(database)
        if isinstance(text, str) and text and text != ":memory:" and not text.startswith("file:"):
            kwargs["uri"] = True
            return _original_connect(Path(text).resolve().as_uri() + "?mode=ro", *args, **kwargs)
    return _original_connect(database, *args, **kwargs)


def install_read_only_guard() -> None:
    """Faz todo ``sqlite3.connect`` por caminho abrir com ``mode=ro`` (idempotente)."""
    if sqlite3.connect is not _connect_read_only:
        sqlite3.connect = _connect_read_only  # type: ignore[assignment]


def uninstall_read_only_guard() -> None:
    """Restaura ``sqlite3.connect`` original (usado em testes)."""
    sqlite3.connect = _original_connect  # type: ignore[assignment]


def apply_cloud_environment() -> bool:
    """Prepara o processo para a nuvem; sem o modo ``cloud`` não faz nada.

    Desliga a sincronização automática, aponta os dados para um diretório
    gravável, descarta qualquer token de arquivo remoto e força o SQLite a
    abrir em somente leitura. Retorna se o modo nuvem está ativo.
    """
    if not is_cloud():
        return False
    os.environ[ENV_DEPLOY_MODE] = CLOUD_VALUE
    os.environ["NBA_AUTO_SYNC"] = "0"
    os.environ.setdefault("NBA_DATA_HOME", CLOUD_DEFAULT_DATA_HOME)
    for name in _TOKEN_ENV_VARS:
        if os.environ.pop(name, None) is not None:
            logger.warning("Token %s ignorado: a versão online nunca usa credenciais.", name)
    install_read_only_guard()
    return True
