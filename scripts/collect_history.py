"""Coleta pública completa desde 2022, retomável e sem chaves de API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.history_sources import collect_history  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.store import DEFAULT_DB_PATH  # noqa: E402


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--start-year", type=int, default=2022, help="Ano final da temporada; 2022 = 2021–22."
    )
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--core", action="store_true", help="Somente conjuntos usados pela visão defensiva.")
    parser.add_argument("--catalog", type=Path, help="Catálogo JSONL público previamente consultado.")
    args = parser.parse_args()
    releases = None
    if args.catalog:
        releases = [json.loads(line) for line in args.catalog.read_text(encoding="utf-8-sig").splitlines()]

    def progress(done: int, total: int, name: str) -> None:
        print(f"[{done}/{total}] {name}", flush=True)

    result = collect_history(
        args.db,
        start_year=args.start_year,
        end_year=args.end_year,
        core=args.core,
        releases=releases,
        progress=progress,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    if result["errors"] or result["normalized"].get("errors"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
