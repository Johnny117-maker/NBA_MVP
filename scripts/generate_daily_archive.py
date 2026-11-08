"""Entrada do coletor agendado, independente de Streamlit e do computador do usuário."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from src.daily_automation import bootstrap_seed, generate_daily_archive
    from src.logging_setup import configure_logging
    from src.remote_archive import GitHubArchive

    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    client = GitHubArchive()
    if not client.token:
        raise SystemExit("A rotina agendada requer GITHUB_TOKEN com acesso a Contents do repositório.")
    bootstrap_seed(args.db, client)
    report = generate_daily_archive(args.db, client, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] in {"incomplete", "source_unavailable"}:
        raise SystemExit(
            "Cobertura incompleta registrada no arquivo diário. Confira o relatório da execução."
        )


if __name__ == "__main__":
    main()
