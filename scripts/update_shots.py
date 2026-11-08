from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# No Windows, a saída padrão cai na codepage local (cp1252) quando redirecionada
# por pipe/arquivo — incapaz de representar nomes de jogador com certas letras
# (ex.: "Dončić", "Jokić"). Sem isso, o script derruba com UnicodeEncodeError no
# meio de uma coleta longa, inclusive no próprio fallback de erro.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.logging_setup import configure_logging  # noqa: E402
from src.shot_connector import fetch_player_shots  # noqa: E402
from src.shot_storage import (  # noqa: E402
    count_player_shots,
    players_missing_shots,
    upsert_player_shots,
)
from src.store import DEFAULT_DB_PATH, init_db  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 100
DEFAULT_DELAY_SECONDS = 0.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa arremessos jogador a jogador por temporada (ShotChartDetail) e "
            "salva em SQLite, sem duplicar. Uma chamada por jogador por temporada — "
            "lento, retomável: rode várias vezes, cada execução continua de onde a "
            "anterior parou."
        )
    )
    parser.add_argument("--seasons", nargs="+", default=None, help="Restringe a temporadas específicas.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Máximo de jogadores (por temporada) a coletar nesta execução (padrão: {DEFAULT_LIMIT}).",
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
            pending.extend(players_missing_shots(args.db, season=season))
    else:
        pending = players_missing_shots(args.db)

    batch = pending[: args.limit]
    print(
        f"{len(pending)} jogadores (por temporada) ainda sem arremessos coletados. "
        f"Coletando até {len(batch)} nesta execução."
    )

    collected = 0
    failed = 0
    for index, (player_id, player_name, season) in enumerate(batch, start=1):
        try:
            shots = fetch_player_shots(player_id, season)
            added = upsert_player_shots(shots, args.db)
            collected += 1
            print(f"  [{index}/{len(batch)}] {player_name} ({season}): {added} arremessos novos")
        except Exception as error:  # nba_api costuma falhar por timeout/bloqueio de rede
            # nba_api costuma falhar por timeout/bloqueio de rede; segue para o próximo jogador.
            logger.warning("Falha ao coletar os arremessos de %s", player_name, exc_info=True)
            failed += 1
            print(f"  [{index}/{len(batch)}] Falha em {player_name} ({season}): {error}")

        time.sleep(args.delay)

    remaining = len(pending) - collected
    print(
        f"Coleta concluída: {collected} jogadores processados, {failed} falharam. "
        f"Total de arremessos no banco: {count_player_shots(args.db)}. "
        f"Ainda faltam aproximadamente {remaining} jogadores — rode de novo para continuar."
    )


if __name__ == "__main__":
    main()
