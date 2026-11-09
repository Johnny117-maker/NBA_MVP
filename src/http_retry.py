"""Retentativas com espera progressiva para consultas a fontes externas.

Só falhas passageiras são repetidas (rede, tempo esgotado e HTTP 429/5xx). Erros definitivos,
como 404 ou um corpo inválido, sobem na primeira tentativa. Cada repetição é registrada em log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (requests.ConnectionError, requests.Timeout)


class TransientHTTPError(requests.RequestException):
    """Resposta HTTP com status passageiro (429/5xx); guarda a resposta para quem esgotar as tentativas."""

    def __init__(self, response: requests.Response):
        super().__init__(f"HTTP {response.status_code}", response=response)
        self.reply = response


def default_sleep(seconds: float) -> None:
    time.sleep(seconds)


def backoff_delays(attempts: int, base_delay: float, max_delay: float) -> list[float]:
    """Esperas entre as tentativas: base, 2×base, 4×base... limitadas a `max_delay`."""
    return [min(max_delay, base_delay * 2**index) for index in range(max(attempts - 1, 0))]


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (*TRANSIENT_ERRORS, TransientHTTPError),
    label: str = "consulta externa",
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Executa `operation`; em falha passageira espera e tenta de novo, até `attempts` vezes.

    A última falha é relançada sem alteração. `sleep` existe para os testes não esperarem de verdade.
    """
    if attempts < 1:
        raise ValueError("attempts deve ser pelo menos 1.")
    wait = sleep or default_sleep
    delays = backoff_delays(attempts, base_delay, max_delay)
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retry_on as error:
            if attempt == attempts:
                raise
            delay = delays[attempt - 1]
            logger.warning(
                "%s falhou (%s); nova tentativa %d/%d em %.1fs",
                label,
                type(error).__name__,
                attempt + 1,
                attempts,
                delay,
            )
            wait(delay)
    raise AssertionError("inalcançável")  # pragma: no cover
