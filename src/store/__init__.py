"""Banco SQLite do projeto: esquema, jogos, previsões e pendências.

O módulo foi dividido por assunto; todos os nomes antigos continuam disponíveis aqui,
então `from src.store import ...` segue funcionando.
"""

from .games import (  # noqa: F401
    apply_game_aliases,
    count_distinct_players,
    count_distinct_teams,
    count_games,
    count_player_games,
    count_team_advanced_stats,
    list_seasons,
    read_dashboard_leaders,
    read_player_games,
    read_raw_games,
    read_team_advanced_stats,
    upsert_games,
    upsert_player_games,
    upsert_team_advanced_stats,
)
from .pending import (  # noqa: F401
    _nba_pending_ids,
    count_players_missing_starter_status,
    games_missing_advanced_stats,
    games_missing_starter_status,
    update_starter_status,
)
from .predictions import (  # noqa: F401
    _normalize_team_key,
    log_model_training,
    log_player_prediction,
    log_team_prediction,
    read_model_training_log,
    read_player_predictions,
    read_team_predictions,
    resolve_player_predictions,
    resolve_team_predictions,
)
from .schema import (  # noqa: F401
    _GAME_COLUMNS,
    _GAMES_SCHEMA,
    _MODEL_TRAINING_LOG_SCHEMA,
    _PLAYER_GAME_COLUMNS,
    _PLAYER_GAME_STATS_SCHEMA,
    _PLAYER_PREDICTIONS_SCHEMA,
    _TEAM_ADVANCED_COLUMNS,
    _TEAM_ADVANCED_STATS_SCHEMA,
    _TEAM_PREDICTIONS_SCHEMA,
    DEFAULT_DB_PATH,
    _migrate_player_game_stats,
    _migrate_player_predictions,
    init_db,
)
