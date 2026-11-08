"""Configuração central de logging do NBA Analytics Lab.

O app (Streamlit) e os scripts chamam `configure_logging()` uma vez na partida.
O nível vem de NBA_LOG_LEVEL (DEBUG, INFO, WARNING, ERROR); o padrão é INFO.
"""

from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LEVEL_ENV = "NBA_LOG_LEVEL"
_HANDLER_FLAG = "_nba_analytics_lab_handler"


def _resolve_level(level: int | str | None) -> int:
    value = level if level is not None else os.environ.get(LEVEL_ENV, "INFO")
    if isinstance(value, int):
        return value
    resolved = logging.getLevelName(str(value).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: int | str | None = None) -> logging.Logger:
    """Configura o logger raiz uma única vez (chamadas repetidas só atualizam o nível).

    Streamlit reexecuta o script a cada interação; por isso a função não duplica handlers.
    """
    root = logging.getLogger()
    resolved = _resolve_level(level)
    if not any(getattr(handler, _HANDLER_FLAG, False) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        setattr(handler, _HANDLER_FLAG, True)
        root.addHandler(handler)
    root.setLevel(resolved)
    return root
