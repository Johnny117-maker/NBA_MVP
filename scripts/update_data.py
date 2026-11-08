from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live_types import current_season  # noqa: E402
from src.logging_setup import configure_logging  # noqa: E402
from src.nba_client import (  # noqa: E402
    fetch_player_season_logs,
    fetch_season_games,
    pair_home_away,
)
from src.store import (  # noqa: E402
    DEFAULT_DB_PATH,
    count_games,
    count_player_games,
    init_db,
    upsert_games,
    upsert_player_games,
)

logger = logging.getLogger(__name__)

_CURRENT_START = int(current_season()[:4])
DEFAULT_SEASONS = [f"{year}-{(year + 1) % 100:02d}" for year in range(_CURRENT_START - 2, _CURRENT_START + 1)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Baixa jogos da NBA via nba_api e salva em SQLite, sem duplicar."
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=DEFAULT_SEASONS,
        help="Temporadas a baixar, ex: 2023-24 2024-25 (padrão: últimas três temporadas).",
    )
    parser.add_argument("--season-type", default="Regular Season")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()
    init_db(args.db)

    for season in args.seasons:
        print(f"Baixando temporada {season} ({args.season_type})...")
        try:
            raw = fetch_season_games(season, season_type=args.season_type)
        except Exception as error:  # nba_api costuma falhar por timeout/bloqueio de rede
            # nba_api costuma falhar por timeout/bloqueio de rede; segue para a próxima temporada.
            logger.warning("Falha ao baixar a temporada %s", season, exc_info=True)
            print(f"  Falha ao baixar {season}: {error}")
            continue

        games = pair_home_away(raw)
        added = upsert_games(games, args.db)
        print(f"  {len(games)} jogos encontrados, {added} novos gravados em {args.db}")

        try:
            player_raw = fetch_player_season_logs(season, season_type=args.season_type)
        except Exception as error:  # nba_api costuma falhar por timeout/bloqueio de rede
            # nba_api costuma falhar por timeout/bloqueio de rede; segue para a próxima temporada.
            logger.warning("Falha ao baixar os jogadores de %s", season, exc_info=True)
            print(f"  Falha ao baixar jogadores de {season}: {error}")
            continue

        added_players = upsert_player_games(player_raw, args.db)
        print(
            f"  {len(player_raw)} linhas de jogadores encontradas, "
            f"{added_players} novas gravadas em {args.db}"
        )

    print(
        f"Coleta concluída. Total de jogos no banco: {count_games(args.db)} | "
        f"linhas de jogadores: {count_player_games(args.db)}"
    )


if __name__ == "__main__":
    main()
