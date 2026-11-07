"""Consultas e modelos compartilhados pelas telas de rodada e palpites."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import streamlit as st

from .daily_games import build_form_table, player_snapshot_context, recent_training_sample
from .data import team_snapshot
from .player_features import add_opponent_context, add_rolling_features
from .player_metrics import player_snapshot
from .player_model import predict_player_game, train_player_models


@st.cache_data(ttl=3600, max_entries=8, show_spinner=False)
def _fetch_schedule(retry_token: int, selected_day: date) -> pd.DataFrame:
    from .nba_schedule import fetch_nba_schedule
    from .schedule_storage import DEFAULT_SCHEDULE_CACHE_PATH, save_schedule_cache

    _ = retry_token  # entra na chave do cache para o botão "Atualizar" forçar nova consulta
    schedule = fetch_nba_schedule(lookahead_days=1, start_date=selected_day)
    try:
        save_schedule_cache(schedule, DEFAULT_SCHEDULE_CACHE_PATH)
    except OSError:
        logging.getLogger(__name__).warning("Não foi possível salvar uma cópia local do calendário.")
    return schedule


def _load_schedule(retry_token: int, selected_day: date) -> tuple[pd.DataFrame, str | None]:
    from .live_store import live_schedule
    from .schedule_storage import DEFAULT_SCHEDULE_CACHE_PATH, read_schedule_cache
    from .store import DEFAULT_DB_PATH

    synchronized = live_schedule(DEFAULT_DB_PATH, selected_day.isoformat())
    if not synchronized.empty:
        return synchronized, None

    try:
        return _fetch_schedule(retry_token, selected_day), None
    except RuntimeError as error:
        # Falhas não ficam no cache de uma hora; a próxima tentativa consulta a rede novamente.
        schedule = read_schedule_cache(DEFAULT_SCHEDULE_CACHE_PATH)
        if not schedule.empty:
            schedule["schedule_source"] = (
                schedule["schedule_source"].fillna("NBA/ESPN") + " (salvo localmente)"
            )
        return schedule, str(error)


@st.cache_resource(show_spinner=False, max_entries=2)
def _load_player_games(db_path: str, updated_at: float, selected_day: date) -> pd.DataFrame:
    from .player_data import load_player_games

    _ = updated_at  # invalida o cache quando o banco é atualizado
    games = load_player_games(source="real", db_path=db_path)
    return games.loc[pd.to_datetime(games["game_date"]).dt.date < selected_day].copy()


@st.cache_data(show_spinner=False, max_entries=2)
def _load_team_games(db_path: str, updated_at: float, selected_day: date) -> pd.DataFrame:
    from .data import load_real_games

    _ = updated_at
    games = load_real_games(db_path)
    return games.loc[pd.to_datetime(games["game_date"]).dt.date < selected_day].copy()


@st.cache_resource(show_spinner="Treinando o modelo de times...", max_entries=2)
def _team_model_context(db_path: str, updated_at: float, selected_day: date):
    from .model import train_models

    games = _load_team_games(db_path, updated_at, selected_day)
    return train_models(games), games


@st.cache_data(ttl=21600, show_spinner=False)
def _load_current_roster() -> pd.DataFrame:
    from .current_roster import fetch_current_roster

    return fetch_current_roster()


@st.cache_data(show_spinner=False, max_entries=2)
def _form_table(
    db_path: str,
    updated_at: float,
    roster_version: str,
    roster_records: tuple[tuple[int, str], ...],
    selected_day: date,
) -> pd.DataFrame:
    # A versão do elenco participa da chave do cache.
    _ = roster_version

    player_games = _load_player_games(db_path, updated_at, selected_day)
    current_roster = pd.DataFrame(
        roster_records,
        columns=["player_id", "team"],
    )

    return build_form_table(
        player_games,
        current_roster=current_roster,
    )


@st.cache_resource(show_spinner="Treinando o modelo de jogadores...", max_entries=2)
def _model_context(db_path: str, updated_at: float, selected_day: date):
    player_games = _load_player_games(db_path, updated_at, selected_day)
    try:
        team_games = _load_team_games(db_path, updated_at, selected_day)
    except (ValueError, FileNotFoundError):
        team_games = None
    training = recent_training_sample(player_games)
    features = add_rolling_features(training)
    if team_games is not None:
        features = add_opponent_context(features, team_games)
    else:
        features["opponent_def_rating"] = 113.0
    return (
        train_player_models(features),
        player_games,
        team_games,
        {
            "rows": len(training),
            "from": training["game_date"].min(),
            "to": training["game_date"].max(),
        },
    )


@st.cache_data(show_spinner=False, ttl=21600, max_entries=256)
def _project_player(
    db_path: str,
    updated_at: float,
    player_id: int,
    opponent_name: str,
    is_home: bool,
    rest_days: int,
    selected_day: date,
) -> dict | None:
    bundle, player_games, team_games, training = _model_context(db_path, updated_at, selected_day)
    opponent_def_rating = None
    if team_games is not None:
        try:
            opponent_def_rating = team_snapshot(team_games, opponent_name, with_elo=False)["def_rating"]
        except (ValueError, KeyError):
            opponent_def_rating = None
    try:
        snapshot = player_snapshot(player_snapshot_context(player_games, player_id), player_id)
        prediction = predict_player_game(
            bundle,
            snapshot,
            is_home=is_home,
            rest_days=rest_days,
            opponent_def_rating=opponent_def_rating,
        )
    except (ValueError, KeyError):
        return None
    return {
        "minutes": prediction.minutes,
        "pts": prediction.stats["pts"],
        "reb": prediction.stats["reb"],
        "ast": prediction.stats["ast"],
        "confidence": prediction.confidence,
        "stats_low": prediction.stats_low,
        "stats_high": prediction.stats_high,
        "training": training,
    }
