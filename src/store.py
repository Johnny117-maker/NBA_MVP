from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("data/nba.db")

_GAMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    game_date TEXT NOT NULL,
    season TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_points INTEGER NOT NULL,
    away_points INTEGER NOT NULL
);
"""

_PLAYER_GAME_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_game_stats (
    game_id TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    season TEXT NOT NULL,
    player_name TEXT NOT NULL,
    team TEXT NOT NULL,
    opponent TEXT NOT NULL,
    is_home INTEGER NOT NULL,
    minutes REAL NOT NULL,
    pts INTEGER NOT NULL,
    oreb INTEGER NOT NULL,
    dreb INTEGER NOT NULL,
    reb INTEGER NOT NULL,
    ast INTEGER NOT NULL,
    stl INTEGER NOT NULL,
    blk INTEGER NOT NULL,
    tov INTEGER NOT NULL,
    pf INTEGER NOT NULL,
    fgm INTEGER NOT NULL,
    fga INTEGER NOT NULL,
    fg3m INTEGER NOT NULL,
    fg3a INTEGER NOT NULL,
    ftm INTEGER NOT NULL,
    fta INTEGER NOT NULL,
    is_starter INTEGER,
    PRIMARY KEY (game_id, player_id)
);
"""

_TEAM_ADVANCED_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_advanced_stats (
    game_id TEXT NOT NULL,
    team TEXT NOT NULL,
    off_rating REAL NOT NULL,
    def_rating REAL NOT NULL,
    net_rating REAL NOT NULL,
    pace REAL NOT NULL,
    PRIMARY KEY (game_id, team)
);
"""

_TEAM_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_win_probability REAL NOT NULL,
    predicted_home_score REAL NOT NULL,
    predicted_away_score REAL NOT NULL,
    confidence TEXT NOT NULL,
    actual_home_score INTEGER,
    actual_away_score INTEGER,
    resolved_at TEXT
);
"""

_PLAYER_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    opponent TEXT,
    is_home INTEGER NOT NULL,
    predicted_minutes REAL NOT NULL,
    predicted_pts REAL NOT NULL,
    predicted_reb REAL NOT NULL,
    predicted_ast REAL NOT NULL,
    confidence TEXT NOT NULL,
    actual_minutes REAL,
    actual_pts REAL,
    actual_reb REAL,
    actual_ast REAL,
    resolved_at TEXT
);
"""

_MODEL_TRAINING_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_training_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trained_at TEXT NOT NULL,
    model_type TEXT NOT NULL,
    n_games INTEGER NOT NULL,
    metrics TEXT NOT NULL
);
"""

_GAME_COLUMNS = [
    "game_id",
    "game_date",
    "season",
    "home_team",
    "away_team",
    "home_points",
    "away_points",
]

_TEAM_ADVANCED_COLUMNS = ["game_id", "team", "off_rating", "def_rating", "net_rating", "pace"]

_PLAYER_GAME_COLUMNS = [
    "game_id",
    "player_id",
    "game_date",
    "season",
    "player_name",
    "team",
    "opponent",
    "is_home",
    "minutes",
    "pts",
    "oreb",
    "dreb",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
]


def _migrate_player_game_stats(connection: sqlite3.Connection) -> None:
    """Adiciona colunas novas a um `player_game_stats` já existente.

    `CREATE TABLE IF NOT EXISTS` não altera uma tabela que já existe — bancos
    coletados antes da coluna `is_starter` existir (Fase 5 da titularidade)
    precisam desse `ALTER TABLE` para ganhá-la sem perder os dados já
    coletados.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(player_game_stats)")}
    if "is_starter" not in columns:
        connection.execute("ALTER TABLE player_game_stats ADD COLUMN is_starter INTEGER")


def init_db(path: Path = DEFAULT_DB_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            _GAMES_SCHEMA
            + _PLAYER_GAME_STATS_SCHEMA
            + _TEAM_ADVANCED_STATS_SCHEMA
            + _TEAM_PREDICTIONS_SCHEMA
            + _PLAYER_PREDICTIONS_SCHEMA
            + _MODEL_TRAINING_LOG_SCHEMA
        )
        _migrate_player_game_stats(connection)


def upsert_games(games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere jogos novos, ignorando os que já existem (mesmo game_id). Retorna quantos entraram."""
    init_db(path)
    rows = games.copy()
    rows["game_date"] = rows["game_date"].astype(str)

    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        connection.executemany(
            """
            INSERT OR IGNORE INTO games
                (game_id, game_date, season, home_team, away_team, home_points, away_points)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows[_GAME_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    return after - before


def read_raw_games(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Banco de dados não encontrado em {path}. "
            "Rode 'python scripts/update_data.py' para coletar os jogos."
        )
    with sqlite3.connect(path) as connection:
        data = pd.read_sql_query("SELECT * FROM games ORDER BY game_date", connection)
    if data.empty:
        raise ValueError("O banco de dados não tem nenhum jogo ainda.")
    data["game_date"] = pd.to_datetime(data["game_date"])
    return data


def count_games(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]


def list_seasons(path: Path = DEFAULT_DB_PATH) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT DISTINCT season FROM games ORDER BY season"
        ).fetchall()
    return [row[0] for row in rows]


def upsert_player_games(player_games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere estatísticas de jogadores novas, ignorando duplicatas (game_id, player_id)."""
    init_db(path)
    rows = player_games.copy()
    rows["game_date"] = rows["game_date"].astype(str)
    rows["is_home"] = rows["is_home"].astype(int)

    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO player_game_stats
                ({", ".join(_PLAYER_GAME_COLUMNS)})
            VALUES ({", ".join("?" for _ in _PLAYER_GAME_COLUMNS)})
            """,
            rows[_PLAYER_GAME_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]
    return after - before


def read_player_games(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Banco de dados não encontrado em {path}. "
            "Rode 'python scripts/update_data.py' para coletar os jogadores."
        )
    with sqlite3.connect(path) as connection:
        data = pd.read_sql_query(
            "SELECT * FROM player_game_stats ORDER BY game_date", connection
        )
    if data.empty:
        raise ValueError("O banco de dados não tem estatísticas de jogadores ainda.")
    data["game_date"] = pd.to_datetime(data["game_date"])
    data["is_home"] = data["is_home"].astype(bool)
    return data


def count_distinct_teams(path: Path = DEFAULT_DB_PATH) -> int:
    """Times distintos que aparecem em `games` (mandante ou visitante) — para
    o cartão "times cadastrados" da Visão Geral, sem precisar carregar os
    jogos inteiros em um DataFrame."""
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM (SELECT home_team AS team FROM games UNION SELECT away_team FROM games)"
        ).fetchone()[0]


def count_distinct_players(path: Path = DEFAULT_DB_PATH) -> int:
    """Jogadores distintos em `player_game_stats` — para o cartão "jogadores
    coletados" da Visão Geral."""
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_game_stats'"
        ).fetchall()
        if not tables:
            return 0
        return connection.execute(
            "SELECT COUNT(DISTINCT player_id) FROM player_game_stats"
        ).fetchone()[0]


def count_player_games(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]


def upsert_team_advanced_stats(advanced_stats: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Insere Rating oficiais novos, ignorando duplicatas (game_id, team)."""
    init_db(path)
    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM team_advanced_stats").fetchone()[0]
        connection.executemany(
            f"""
            INSERT OR IGNORE INTO team_advanced_stats
                ({", ".join(_TEAM_ADVANCED_COLUMNS)})
            VALUES ({", ".join("?" for _ in _TEAM_ADVANCED_COLUMNS)})
            """,
            advanced_stats[_TEAM_ADVANCED_COLUMNS].itertuples(index=False, name=None),
        )
        connection.commit()
        after = connection.execute("SELECT COUNT(*) FROM team_advanced_stats").fetchone()[0]
    return after - before


def read_team_advanced_stats(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=_TEAM_ADVANCED_COLUMNS)
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='team_advanced_stats'"
        ).fetchall()
        if not tables:
            return pd.DataFrame(columns=_TEAM_ADVANCED_COLUMNS)
        return pd.read_sql_query("SELECT * FROM team_advanced_stats", connection)


def count_team_advanced_stats(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='team_advanced_stats'"
        ).fetchall()
        if not tables:
            return 0
        return connection.execute("SELECT COUNT(*) FROM team_advanced_stats").fetchone()[0]


def log_team_prediction(
    home_team: str,
    away_team: str,
    home_win_probability: float,
    predicted_home_score: float,
    predicted_away_score: float,
    confidence: str,
    path: Path = DEFAULT_DB_PATH,
) -> int:
    """Registra uma previsão de time. Retorna o id da linha criada."""
    init_db(path)
    created_at = datetime.now().isoformat()
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO team_predictions
                (created_at, home_team, away_team, home_win_probability,
                 predicted_home_score, predicted_away_score, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                home_team,
                away_team,
                home_win_probability,
                predicted_home_score,
                predicted_away_score,
                confidence,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def read_team_predictions(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='team_predictions'"
        ).fetchall()
        if not tables:
            return pd.DataFrame()
        data = pd.read_sql_query(
            "SELECT * FROM team_predictions ORDER BY created_at DESC", connection
        )
    if not data.empty:
        data["created_at"] = pd.to_datetime(data["created_at"])
        data["resolved_at"] = pd.to_datetime(data["resolved_at"])
    return data


def resolve_team_predictions(games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Casa previsões pendentes com o primeiro jogo real correspondente depois do registro.

    Retorna quantas previsões foram resolvidas nesta chamada.
    """
    predictions = read_team_predictions(path)
    if predictions.empty:
        return 0

    pending = predictions[predictions["resolved_at"].isna()]
    if pending.empty:
        return 0

    games = games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"])
    resolved_at = datetime.now().isoformat()

    resolved_count = 0
    with sqlite3.connect(path) as connection:
        for _, prediction in pending.iterrows():
            candidates = games[
                (games["home_team"] == prediction["home_team"])
                & (games["away_team"] == prediction["away_team"])
                & (games["game_date"] > prediction["created_at"])
            ].sort_values("game_date")
            if candidates.empty:
                continue

            match = candidates.iloc[0]
            connection.execute(
                """
                UPDATE team_predictions
                SET actual_home_score = ?, actual_away_score = ?, resolved_at = ?
                WHERE id = ?
                """,
                (
                    int(match["home_points"]),
                    int(match["away_points"]),
                    resolved_at,
                    int(prediction["id"]),
                ),
            )
            resolved_count += 1
        connection.commit()
    return resolved_count


def log_player_prediction(
    player_id: int,
    player_name: str,
    opponent: str | None,
    is_home: bool,
    predicted_minutes: float,
    predicted_pts: float,
    predicted_reb: float,
    predicted_ast: float,
    confidence: str,
    path: Path = DEFAULT_DB_PATH,
) -> int:
    """Registra uma previsão de jogador. Retorna o id da linha criada.

    `opponent` é guardado só como contexto — a resolução casa pelo próximo
    jogo real do jogador (`resolve_player_predictions`), não exige que o
    adversário real seja o mesmo escolhido na hora da previsão (que é
    hipotético, não vem de uma agenda real de jogos futuros).
    """
    init_db(path)
    created_at = datetime.now().isoformat()
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO player_predictions
                (created_at, player_id, player_name, opponent, is_home,
                 predicted_minutes, predicted_pts, predicted_reb, predicted_ast, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                int(player_id),
                player_name,
                opponent,
                int(is_home),
                predicted_minutes,
                predicted_pts,
                predicted_reb,
                predicted_ast,
                confidence,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def read_player_predictions(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_predictions'"
        ).fetchall()
        if not tables:
            return pd.DataFrame()
        data = pd.read_sql_query(
            "SELECT * FROM player_predictions ORDER BY created_at DESC", connection
        )
    if not data.empty:
        data["created_at"] = pd.to_datetime(data["created_at"])
        data["resolved_at"] = pd.to_datetime(data["resolved_at"])
        data["is_home"] = data["is_home"].astype(bool)
    return data


def resolve_player_predictions(player_games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Casa previsões pendentes com o próximo jogo real do mesmo jogador.

    Diferente de `resolve_team_predictions` (que exige o mesmo mandante ×
    visitante), aqui o critério é só `player_id` — o adversário escolhido na
    hora da previsão é hipotético, então exigir que bata com o adversário
    real deixaria quase tudo pendente para sempre. Retorna quantas previsões
    foram resolvidas nesta chamada.
    """
    predictions = read_player_predictions(path)
    if predictions.empty:
        return 0

    pending = predictions[predictions["resolved_at"].isna()]
    if pending.empty:
        return 0

    games = player_games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"])
    resolved_at = datetime.now().isoformat()

    resolved_count = 0
    with sqlite3.connect(path) as connection:
        for _, prediction in pending.iterrows():
            candidates = games[
                (games["player_id"] == prediction["player_id"])
                & (games["game_date"] > prediction["created_at"])
            ].sort_values("game_date")
            if candidates.empty:
                continue

            match = candidates.iloc[0]
            connection.execute(
                """
                UPDATE player_predictions
                SET actual_minutes = ?, actual_pts = ?, actual_reb = ?, actual_ast = ?,
                    resolved_at = ?
                WHERE id = ?
                """,
                (
                    float(match["minutes"]),
                    float(match["pts"]),
                    float(match["reb"]),
                    float(match["ast"]),
                    resolved_at,
                    int(prediction["id"]),
                ),
            )
            resolved_count += 1
        connection.commit()
    return resolved_count


def log_model_training(
    model_type: str, n_games: int, metrics: dict, path: Path = DEFAULT_DB_PATH
) -> int:
    """Registra uma rodada de (re)treinamento. Retorna o id da linha criada."""
    init_db(path)
    trained_at = datetime.now().isoformat()
    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO model_training_log (trained_at, model_type, n_games, metrics)
            VALUES (?, ?, ?, ?)
            """,
            (trained_at, model_type, n_games, json.dumps(metrics)),
        )
        connection.commit()
        return int(cursor.lastrowid)


def read_model_training_log(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='model_training_log'"
        ).fetchall()
        if not tables:
            return pd.DataFrame()
        data = pd.read_sql_query(
            "SELECT * FROM model_training_log ORDER BY trained_at DESC", connection
        )
    if not data.empty:
        data["trained_at"] = pd.to_datetime(data["trained_at"])
        data["metrics"] = data["metrics"].apply(json.loads)
    return data


def games_missing_advanced_stats(path: Path = DEFAULT_DB_PATH, season: str | None = None) -> list:
    """Game_ids de `games` que ainda não têm Rating oficial coletado."""
    init_db(path)
    with sqlite3.connect(path) as connection:
        query = """
            SELECT DISTINCT g.game_id FROM games g
            WHERE g.game_id NOT IN (SELECT game_id FROM team_advanced_stats)
        """
        params: tuple = ()
        if season is not None:
            query += " AND g.season = ?"
            params = (season,)
        query += " ORDER BY g.game_date"
        rows = connection.execute(query, params).fetchall()
    return [row[0] for row in rows]


def games_missing_starter_status(path: Path = DEFAULT_DB_PATH, season: str | None = None) -> list:
    """Game_ids de `player_game_stats` com pelo menos uma linha sem titularidade coletada."""
    init_db(path)
    with sqlite3.connect(path) as connection:
        query = "SELECT DISTINCT game_id FROM player_game_stats WHERE is_starter IS NULL"
        params: tuple = ()
        if season is not None:
            query += " AND season = ?"
            params = (season,)
        query += " ORDER BY game_date"
        rows = connection.execute(query, params).fetchall()
    return [row[0] for row in rows]


def update_starter_status(rows: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Grava titularidade (titular/reserva) de jogadores num jogo já coletado.

    `rows` precisa ter as colunas `game_id`, `player_id`, `is_starter`. Só
    atualiza linhas que já existem em `player_game_stats` (o boxscore em si
    já foi coletado por `update_data.py`); não insere jogador novo. Retorna
    quantas linhas foram efetivamente atualizadas.
    """
    init_db(path)
    updated = 0
    with sqlite3.connect(path) as connection:
        for row in rows.itertuples(index=False):
            cursor = connection.execute(
                "UPDATE player_game_stats SET is_starter = ? WHERE game_id = ? AND player_id = ?",
                (int(row.is_starter), row.game_id, int(row.player_id)),
            )
            updated += cursor.rowcount
        connection.commit()
    return updated


def count_players_missing_starter_status(path: Path = DEFAULT_DB_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM player_game_stats WHERE is_starter IS NULL"
        ).fetchone()[0]
