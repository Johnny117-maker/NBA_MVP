from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_DB_PATH = Path("data/nba.db")


def read_dashboard_leaders(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Líderes em pontos da temporada mais recente coletada, mínimo de 10 jogos.

    Agrega no SQLite para a abertura do painel não carregar todos os boxscores.
    A equipe é a última registrada nessa temporada, incluindo jogadores trocados.
    """
    if not Path(path).exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_game_stats'"
        ).fetchone()
        if not exists:
            return pd.DataFrame()
        return pd.read_sql_query(
            """
            WITH recent AS (
                SELECT * FROM player_game_stats
                WHERE season = (SELECT season FROM player_game_stats ORDER BY game_date DESC LIMIT 1)
            ), leaders AS (
                SELECT player_id, season, COUNT(*) AS games, AVG(pts) AS pts,
                       AVG(reb) AS reb, AVG(ast) AS ast
                FROM recent GROUP BY player_id, season HAVING COUNT(*) >= 10
                ORDER BY pts DESC, player_id LIMIT 4
            )
            SELECT l.*, r.player_name, r.team FROM leaders l
            JOIN player_game_stats r ON r.rowid = (
                SELECT rowid FROM player_game_stats p WHERE p.player_id = l.player_id
                AND p.season = l.season ORDER BY p.game_date DESC, p.game_id DESC LIMIT 1
            ) ORDER BY l.pts DESC, l.player_id
            """, connection,
        )

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
    target_game_date TEXT,
    predicted_minutes REAL NOT NULL,
    predicted_pts REAL NOT NULL,
    predicted_reb REAL NOT NULL,
    predicted_ast REAL NOT NULL,
    confidence TEXT NOT NULL,
    actual_game_date TEXT,
    actual_opponent TEXT,
    actual_is_home INTEGER,
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


def _migrate_player_predictions(connection: sqlite3.Connection) -> None:
    """Adiciona campos de data/alvo e contexto real sem descartar previsões antigas."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(player_predictions)")}
    migrations = {
        "target_game_date": "TEXT",
        "actual_game_date": "TEXT",
        "actual_opponent": "TEXT",
        "actual_is_home": "INTEGER",
    }
    for column, sql_type in migrations.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE player_predictions ADD COLUMN {column} {sql_type}"
            )


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
        _migrate_player_predictions(connection)


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
        # lastrowid só é None depois de um comando que não seja INSERT — nunca
        # o caso aqui, mas a assinatura do stdlib permite None.
        assert cursor.lastrowid is not None
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
    target_game_date=None,
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
                (created_at, player_id, player_name, opponent, is_home, target_game_date,
                 predicted_minutes, predicted_pts, predicted_reb, predicted_ast, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                int(player_id),
                player_name,
                opponent,
                int(is_home),
                str(target_game_date)[:10] if target_game_date is not None else None,
                predicted_minutes,
                predicted_pts,
                predicted_reb,
                predicted_ast,
                confidence,
            ),
        )
        connection.commit()
        # lastrowid só é None depois de um comando que não seja INSERT — nunca
        # o caso aqui, mas a assinatura do stdlib permite None.
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)


def read_player_predictions(path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    # Executa migrações aditivas em bases anteriores à coluna de data-alvo.
    init_db(path)
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
        data["created_at"] = pd.to_datetime(data["created_at"], errors="coerce")
        data["resolved_at"] = pd.to_datetime(data["resolved_at"], errors="coerce")
        for column in ("target_game_date", "actual_game_date"):
            if column in data.columns:
                data[column] = pd.to_datetime(data[column], errors="coerce")
        data["is_home"] = data["is_home"].astype(bool)
        if "actual_is_home" in data.columns:
            data["actual_is_home"] = data["actual_is_home"].astype("boolean")
    return data


def _normalize_team_key(value: object) -> str:
    """Normaliza nome completo e sigla NBA para permitir comparar adversários."""
    import re

    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    try:
        from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
        lookup = {abbr.casefold(): name for abbr, name in TEAM_ABBREVIATION_TO_NAME.items()}
        text = lookup.get(text.casefold(), text)
    except ImportError:
        pass
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def resolve_player_predictions(player_games: pd.DataFrame, path: Path = DEFAULT_DB_PATH) -> int:
    """Resolve previsões com a partida alvo, evitando casar uma previsão com outro jogo.

    Previsões novas usam `target_game_date` + adversário + mando quando esses
    campos estão disponíveis. Para previsões antigas sem data-alvo, tenta
    casar adversário/mando; só usa o próximo jogo por data quando o DataFrame
    de origem não dispõe dessas colunas (compatibilidade com bases antigas/testes).
    """
    predictions = read_player_predictions(path)
    if predictions.empty:
        return 0

    pending = predictions[predictions["resolved_at"].isna()]
    if pending.empty:
        return 0

    games = player_games.copy()
    if "game_date" not in games.columns or "player_id" not in games.columns:
        return 0
    games["game_date"] = pd.to_datetime(games["game_date"], errors="coerce")
    games["_game_day"] = games["game_date"].dt.normalize()
    games["_opponent_key"] = (
        games["opponent"].map(_normalize_team_key)
        if "opponent" in games.columns
        else ""
    )
    resolved_at = datetime.now().isoformat()
    resolved_count = 0

    with sqlite3.connect(path) as connection:
        for _, prediction in pending.iterrows():
            player_rows = games[games["player_id"] == prediction["player_id"]].copy()
            if player_rows.empty:
                continue

            target_date = prediction.get("target_game_date")
            has_target_date = target_date is not None and not pd.isna(target_date)
            if has_target_date:
                target_day = pd.Timestamp(target_date).normalize()
                candidates = player_rows[player_rows["_game_day"] == target_day]
            else:
                created_at = pd.to_datetime(prediction["created_at"], errors="coerce")
                candidates = player_rows[player_rows["game_date"] > created_at]

            if candidates.empty:
                continue

            expected_opponent = _normalize_team_key(prediction.get("opponent"))
            has_actual_opponent = "opponent" in candidates.columns
            if expected_opponent and has_actual_opponent:
                opponent_matches = candidates[
                    candidates["_opponent_key"] == expected_opponent
                ]
                if not opponent_matches.empty:
                    candidates = opponent_matches
                elif has_target_date or {"is_home"} <= set(candidates.columns):
                    # Não produzir um falso acerto ligando a previsão a outro jogo.
                    continue

            if "is_home" in candidates.columns:
                home_matches = candidates[
                    candidates["is_home"].astype(bool) == bool(prediction["is_home"])
                ]
                if not home_matches.empty:
                    candidates = home_matches
                else:
                    # Mando informado e mando real discordam; não atribuir esse jogo.
                    continue

            match = candidates.sort_values("game_date").iloc[0]
            actual_opponent = (
                str(match["opponent"])
                if "opponent" in match.index and pd.notna(match["opponent"])
                else None
            )
            actual_is_home = (
                int(bool(match["is_home"]))
                if "is_home" in match.index and pd.notna(match["is_home"])
                else None
            )

            connection.execute(
                """
                UPDATE player_predictions
                SET actual_game_date = ?, actual_opponent = ?, actual_is_home = ?,
                    actual_minutes = ?, actual_pts = ?, actual_reb = ?, actual_ast = ?,
                    resolved_at = ?
                WHERE id = ?
                """,
                (
                    pd.Timestamp(match["game_date"]).date().isoformat(),
                    actual_opponent,
                    actual_is_home,
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
        # lastrowid só é None depois de um comando que não seja INSERT — nunca
        # o caso aqui, mas a assinatura do stdlib permite None.
        assert cursor.lastrowid is not None
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
