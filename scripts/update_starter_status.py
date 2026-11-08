from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.logging_setup import configure_logging  # noqa: E402
from src.nba_client import fetch_game_starters  # noqa: E402
from src.store import (  # noqa: E402
    DEFAULT_DB_PATH,
    count_players_missing_starter_status,
    games_missing_starter_status,
    init_db,
    update_starter_status,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 200
DEFAULT_DELAY_SECONDS = 0.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa titularidade (titular/reserva) jogo a jogo (BoxScoreTraditionalV3) "
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
    configure_logging()
    args = parse_args()
    init_db(args.db)

    if args.seasons:
        pending = []
        for season in args.seasons:
            pending.extend(games_missing_starter_status(args.db, season=season))
    else:
        pending = games_missing_starter_status(args.db)

    batch = pending[: args.limit]
    print(
        f"{len(pending)} jogos ainda sem titularidade coletada. "
        f"Coletando até {len(batch)} nesta execução."
    )

    collected = 0
    failed = 0
    for index, game_id in enumerate(batch, start=1):
        try:
            starters = fetch_game_starters(game_id)
            update_starter_status(starters, args.db)
            collected += 1
        except Exception as error:  # nba_api costuma falhar por timeout/bloqueio de rede
            # nba_api costuma falhar por timeout/bloqueio de rede; segue para o próximo item.
            logger.warning("Falha ao coletar a titularidade", exc_info=True)
            failed += 1
            print(f"  [{index}/{len(batch)}] Falha em {game_id}: {error}")

        if index % 25 == 0:
            print(f"  [{index}/{len(batch)}] processados ({collected} ok, {failed} falharam)...")

        time.sleep(args.delay)

    remaining = count_players_missing_starter_status(args.db)
    print(
        f"Coleta concluída: {collected} jogos novos, {failed} falharam. "
        f"Ainda faltam aproximadamente {remaining} linhas de jogador — rode de novo para continuar."
    )


if __name__ == "__main__":
    main()
