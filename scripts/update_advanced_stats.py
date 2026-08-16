from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.nba_client import fetch_game_advanced_stats  # noqa: E402
from src.store import (  # noqa: E402
    DEFAULT_DB_PATH,
    count_team_advanced_stats,
    games_missing_advanced_stats,
    init_db,
    upsert_team_advanced_stats,
)

DEFAULT_LIMIT = 200
DEFAULT_DELAY_SECONDS = 0.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa Offensive/Defensive Rating oficiais jogo a jogo (BoxScoreAdvancedV3) "
            "e salva em SQLite, sem duplicar. Uma chamada por jogo — lento, retomável: "
            "rode várias vezes, cada execução continua de onde a anterior parou."
        )
    )
    parser.add_argument("--seasons", nargs="+", default=None, help="Restringe a temporadas específicas.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Máximo de jogos a coletar nesta execução (padrão: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Segundos de espera entre chamadas, para não sobrecarregar a API.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    init_db(args.db)

    if args.seasons:
        pending = []
        for season in args.seasons:
            pending.extend(games_missing_advanced_stats(args.db, season=season))
    else:
        pending = games_missing_advanced_stats(args.db)

    batch = pending[: args.limit]
    print(
        f"{len(pending)} jogos ainda sem Rating oficial. "
        f"Coletando até {len(batch)} nesta execução."
    )

    collected = 0
    failed = 0
    for index, game_id in enumerate(batch, start=1):
        try:
            advanced = fetch_game_advanced_stats(game_id)
            upsert_team_advanced_stats(advanced, args.db)
            collected += 1
        except Exception as error:  # nba_api costuma falhar por timeout/bloqueio de rede
            failed += 1
            print(f"  [{index}/{len(batch)}] Falha em {game_id}: {error}")

        if index % 25 == 0:
            print(f"  [{index}/{len(batch)}] processados ({collected} ok, {failed} falharam)...")

        time.sleep(args.delay)

    remaining = len(pending) - collected
    print(
        f"Coleta concluída: {collected} jogos novos, {failed} falharam. "
        f"Total no banco: {count_team_advanced_stats(args.db)}. "
        f"Ainda faltam aproximadamente {remaining} jogos — rode de novo para continuar."
    )


if __name__ == "__main__":
    main()
