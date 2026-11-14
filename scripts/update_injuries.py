"""Atualiza o boletim de lesões na base (usado pelo data-refresh antes de gerar o pacote online).

Falha de fonte não derruba a execução: o boletim anterior continua valendo até 48 horas.
Código de saída: 0 = boletim obtido; 1 = nenhuma fonte respondeu (a base fica como estava).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.injuries import refresh_injuries  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.store import DEFAULT_DB_PATH  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args(argv)
    attempt = refresh_injuries(args.db, force=True)
    print(json.dumps(attempt, ensure_ascii=False, indent=2), flush=True)
    return 0 if attempt.get("available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
