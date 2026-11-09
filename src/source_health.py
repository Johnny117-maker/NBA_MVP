"""Estado de cada fonte externa: última resposta bem-sucedida e último erro (página Sistema)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .live_store import get_state, set_state
from .live_types import utc_now

logger = logging.getLogger(__name__)

STATE_KEY = "source_health"


def record_source_result(db_path: str | Path, source: str, error: str | None = None) -> None:
    """Registra sucesso (`error=None`) ou falha de uma fonte. Nunca interrompe quem chamou."""
    try:
        health = get_state(db_path, STATE_KEY, {})
        entry = dict(health.get(source, {}))
        if error is None:
            entry["last_ok"] = utc_now().isoformat()
        else:
            entry["last_error"] = utc_now().isoformat()
            entry["last_error_type"] = error[:120]
        health[source] = entry
        set_state(db_path, STATE_KEY, health)
    except (sqlite3.Error, OSError, ValueError):
        # O estado das fontes é informativo: falha ao gravá-lo não pode derrubar a coleta.
        logger.warning("Não foi possível registrar o estado da fonte %s", source, exc_info=True)


def read_source_health(db_path: str | Path) -> dict[str, dict]:
    """Estado salvo por fonte; vazio quando nada foi registrado ou o arquivo não pode ser lido."""
    try:
        health = get_state(db_path, STATE_KEY, {})
    except (sqlite3.Error, OSError, ValueError):
        logger.warning("Não foi possível ler o estado das fontes", exc_info=True)
        return {}
    return health if isinstance(health, dict) else {}
