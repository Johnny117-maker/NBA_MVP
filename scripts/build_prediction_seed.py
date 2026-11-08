"""Empacota apenas estatísticas públicas para o coletor GitHub, sem fotos pessoais ou chaves."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from src.desktop_seed import build_seed
    from src.logging_setup import configure_logging

    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("O pacote de destino já existe. Use outro nome para preservar o anterior.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prediction-seed-", dir=args.output.parent) as directory:
        target = Path(directory) / "nba.db"
        counts = build_seed(args.source, target, shot_limit=0, include_history=False)
        with sqlite3.connect(target) as db:
            for table in ("team_predictions", "player_predictions", "model_training_log"):
                if db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                    raise RuntimeError("A base distribuível deve excluir previsões pessoais.")
        db.close()
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in Path(directory).iterdir():
                if file.name in {"nba.db", "nba_sync.sqlite"}:
                    archive.write(file, file.name)
        gc.collect()
    with args.output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    args.output.with_name(args.output.name + ".sha256").write_text(
        digest + "  " + args.output.name + "\n", encoding="ascii"
    )
    print(json.dumps({"counts": counts, "bytes": args.output.stat().st_size, "sha256": digest}, indent=2))


if __name__ == "__main__":
    main()
