"""Atualização diária sem o aplicativo aberto: baixa os jogos encerrados e confere o dia anterior.

Códigos de saída: 0 = base atualizada; 2 = a fonte ainda não publicou todos os jogos do
dia anterior; 3 = nenhuma fonte respondeu.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.daily_update import DEFAULT_ATTEMPTS, DEFAULT_WAIT_SECONDS, run_daily_update  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.provider_settings import load_api_keys  # noqa: E402
from src.store import DEFAULT_DB_PATH  # noqa: E402

EXIT_CODES = {"ok": 0, "incomplete": 2, "source_unavailable": 3}


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help="Tentativas se o dia anterior estiver incompleto.",
    )
    parser.add_argument("--wait-minutes", type=float, default=DEFAULT_WAIT_SECONDS / 60)
    args = parser.parse_args(argv)
    report = run_daily_update(
        args.db, load_api_keys(), attempts=args.attempts, wait_seconds=args.wait_minutes * 60
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return EXIT_CODES[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
