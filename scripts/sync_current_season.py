"""Atualiza a temporada atual sem cadastro; --watch mantém a coleta em execução."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.provider_settings import load_api_keys  # noqa: E402
from src.season_sync import SeasonSync  # noqa: E402
from src.store import DEFAULT_DB_PATH  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e encerra (padrão).")
    args = parser.parse_args()
    service = SeasonSync(args.db, load_api_keys())
    try:
        while True:
            result = service.run_once()
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            if not args.watch:
                break
            time.sleep(30)
    except KeyboardInterrupt:
        service.stop()


if __name__ == "__main__":
    main()
