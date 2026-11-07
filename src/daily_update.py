"""Atualização ao fim do dia: importa os jogos encerrados e confere se o dia anterior está completo.

Pensada para rodar sozinha, sem o aplicativo aberto (veja `scripts/update_daily.py` e
`docs/ATUALIZACAO_DIARIA.md`). As fontes públicas costumam publicar os jogos da noite
com algumas horas de atraso, então a rotina repete a consulta enquanto o dia anterior
estiver incompleto.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from .live_providers import ApiKeys
from .live_store import read_live_games, set_state
from .live_types import EASTERN, utc_now
from .season_sync import SeasonSync

DEFAULT_ATTEMPTS = 3
DEFAULT_WAIT_SECONDS = 20 * 60


def day_coverage(db_path: str | Path, day: date) -> dict:
    """Compara os jogos do dia vistos na fonte com os gravados na base de treino.

    `complete`: todos os jogos da fonte terminaram e estão na base. `incomplete`:
    há jogo ainda sem resultado final ou finalizado que não entrou na base.
    `no_games`: a fonte não lista jogos da temporada regular nesse dia.
    """
    scheduled = [
        game
        for game in read_live_games(db_path, day.isoformat())
        if game.regular_season and game.state != "unavailable"
    ]
    finals = [game for game in scheduled if game.state == "final"]
    saved = 0
    if Path(db_path).exists():
        with sqlite3.connect(db_path, timeout=15) as connection:
            saved = int(
                connection.execute(
                    "SELECT COUNT(*) FROM games WHERE substr(game_date, 1, 10)=?", (day.isoformat(),)
                ).fetchone()[0]
            )
    pending = len(scheduled) - len(finals)
    missing = max(0, len(finals) - saved)
    if not scheduled:
        status = "no_games"
    elif pending == 0 and missing == 0:
        status = "complete"
    else:
        status = "incomplete"
    return {
        "day": day.isoformat(),
        "scheduled": len(scheduled),
        "finals": len(finals),
        "pending": pending,
        "saved": saved,
        "missing": missing,
        "status": status,
    }


def last_game_day(db_path: str | Path) -> str | None:
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(db_path, timeout=15) as connection:
        value = connection.execute("SELECT MAX(substr(game_date, 1, 10)) FROM games").fetchone()[0]
    return str(value) if value else None


def run_daily_update(
    db_path: str | Path,
    keys: ApiKeys | None = None,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Sincroniza a temporada e repete até o dia anterior (fuso Eastern) estar completo.

    Status final: `ok` (dia anterior completo ou sem jogos), `incomplete` (a fonte
    ainda não publicou todos os resultados) ou `source_unavailable` (nenhuma fonte
    respondeu nesta execução).
    """
    db_path = Path(db_path)
    started = utc_now()
    service = SeasonSync(db_path, keys, archive_analysis=False)
    report: dict = {"started_at": started.isoformat(), "attempts": []}
    reached_source = False
    coverage: dict = {}
    for attempt in range(1, max(1, attempts) + 1):
        day = utc_now().astimezone(EASTERN).date()
        # Ignora o cache de uma hora do arquivo público: queremos o dado mais novo.
        service.request_refresh()
        sync = service.run_once(day)
        coverage = day_coverage(db_path, day - timedelta(days=1))
        succeeded_at = sync.get("archive_success_at") or sync.get("live_success_at")
        reached_source = reached_source or bool(succeeded_at and succeeded_at >= started.isoformat())
        report["attempts"].append(
            {
                "attempt": attempt,
                "changed_games": int(sync.get("changed_games", 0)),
                "errors": list(sync.get("errors", [])),
                "rejected_games": list(sync.get("rejected_games", [])),
                "previous_day": coverage,
            }
        )
        if coverage["status"] != "incomplete" or attempt >= max(1, attempts):
            break
        sleep(wait_seconds)

    resolved = 0
    try:
        from .analysis_archive import resolve_snapshots

        resolved = resolve_snapshots(db_path)
    except (sqlite3.Error, OSError, ValueError, KeyError):
        # Comparar palpites antigos é secundário: não deve derrubar a atualização dos jogos.
        resolved = 0

    report["status"] = (
        "source_unavailable"
        if not reached_source
        else "incomplete"
        if coverage.get("status") == "incomplete"
        else "ok"
    )
    report["previous_day"] = coverage
    report["last_game_day"] = last_game_day(db_path)
    report["snapshots_resolved"] = resolved
    report["finished_at"] = utc_now().isoformat()
    set_state(db_path, "daily_update", report)
    return report
