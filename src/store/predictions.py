"""Previsões registradas de times e jogadores, resolução com os resultados e log de treino."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from .schema import DEFAULT_DB_PATH, init_db


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
