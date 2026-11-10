"""Gera o pacote enxuto para a versão online e, opcionalmente, o pacote da base completa.

Exemplo::

    python scripts/build_serving_bundle.py --db data/nba.db --output-dir dist/data-release \\
        --full-archive dist/data-release/nba-full.tar.gz

Saídas: ``nba-serving-<versão>.tar.gz`` e ``manifest.json`` (versão, data, tamanhos e
SHA-256). O relatório impresso traz os tamanhos **reais** frente às metas (300 MiB
descompactado / 100 MiB compactado). Com a base sintética dos testes esses números não
dizem nada sobre produção: rode com o ``data/nba.db`` real.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.logging_setup import configure_logging  # noqa: E402
from src.serving_bundle import (  # noqa: E402
    BundleBuildError,
    build_serving_bundle,
    pack_full_data,
    size_report,
)
from src.store import DEFAULT_DB_PATH  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="nba.db de origem")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", help="padrão: carimbo UTC (AAAAMMDDTHHMMSSZ)")
    parser.add_argument(
        "--min-shot-season",
        help="opcional: descarta arremessos de temporadas anteriores (ex.: 2022-23) para reduzir o tamanho",
    )
    parser.add_argument(
        "--no-history-files",
        action="store_true",
        help="não inclui os parquet de history/ (as páginas de defesa mostram 'não coletado')",
    )
    parser.add_argument("--full-archive", type=Path, help="também grava a base completa (.tar.gz) aqui")
    args = parser.parse_args(argv)
    try:
        manifest = build_serving_bundle(
            args.db,
            args.output_dir,
            version=args.version,
            min_shot_season=args.min_shot_season,
            include_history=not args.no_history_files,
        )
        print(size_report(manifest))
        if args.full_archive:
            checksum = pack_full_data(args.db, args.full_archive)
            Path(str(args.full_archive) + ".sha256").write_text(
                f"{checksum}  {args.full_archive.name}\n", encoding="utf-8"
            )
            print(f"Base completa: {args.full_archive.stat().st_size / 1024 / 1024:.2f} MiB")
    except BundleBuildError as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
