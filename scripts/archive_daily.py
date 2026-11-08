"""Arquivo pré-jogo e treino de props; usa a mesma trava do monitor automático."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis_archive import run_daily_analysis  # noqa: E402
from src.live_store import acquire_lease, release_lease  # noqa: E402
from src.live_types import EASTERN, utc_now  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.prop_training import ensure_props_bundle, load_research_history  # noqa: E402
from src.research_feeds import fetch_rapm_inputs  # noqa: E402
from src.shot_quality import train_location_quality  # noqa: E402
from src.store import DEFAULT_DB_PATH  # noqa: E402


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Preserva previsões pré-jogo e treina modelos temporais.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--train-only", action="store_true")
    parser.add_argument("--shot-quality", action="store_true")
    parser.add_argument("--rapm-game", help="Coleta PBP/rotações de um ID oficial NBA para auditoria.")
    args = parser.parse_args()
    owner = f"{os.getpid()}:{uuid.uuid4().hex}"
    if not acquire_lease(args.db, owner, ttl=600):
        print("O monitor está atualizando a base. Aguarde o ciclo terminar e execute novamente.")
        return
    try:
        day = utc_now().astimezone(EASTERN).date().isoformat()
        if args.train_only:
            history = load_research_history(args.db, day)
            result = ensure_props_bundle(history, args.db.parent.parent / "models" / "props").manifest
        elif args.shot_quality:
            result = train_location_quality(args.db, args.db.parent.parent / "models" / "research", day)
        elif args.rapm_game:
            result = {
                "files": [str(p) for p in fetch_rapm_inputs(args.rapm_game, args.db.parent / "research")]
            }
        else:
            result = run_daily_analysis(args.db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        release_lease(args.db, owner)


if __name__ == "__main__":
    main()
