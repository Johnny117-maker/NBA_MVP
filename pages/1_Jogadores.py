from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data import generate_demo_games, load_real_games
from src.nba_schedule import fetch_nba_schedule
from src.player_data import load_player_games
from src.player_features import (
    add_opponent_context,
    add_rolling_features,
)
from src.player_index import build_player_index
from src.player_metrics import list_players, player_season_summary
from src.player_model import (
    train_player_models,
)
from src.store import DEFAULT_DB_PATH, count_player_games
from src.ui import components, players_projection, players_tabs, states, theme

st.set_page_config(
    page_title="Jogadores — NBA Analytics Lab",
    page_icon="🧮",
    layout="wide",
)

theme.inject_base_style("players")

components.page_header(
    "Cada jogador tem uma história.",
    "Encontre atletas, acompanhe a evolução e compare produção, eficiência e projeções.",
    category="JOGADORES",
)

real_data_available = DEFAULT_DB_PATH.exists() and count_player_games(DEFAULT_DB_PATH) > 0
db_version = DEFAULT_DB_PATH.stat().st_mtime_ns if DEFAULT_DB_PATH.exists() else 0

with st.expander("Fonte e opções da análise", expanded=False):
    st.subheader("Fonte da análise")
    source_label = st.radio(
        "Fonte dos dados",
        ["Base demonstrativa", "Dados reais (coletados)"],
        index=1 if real_data_available else 0,
        help=(
            "A base demonstrativa é sintética. Dados reais exigem rodar "
            "'python scripts/update_data.py' antes."
        ),
    )

source = "demo" if source_label == "Base demonstrativa" else "real"


@st.cache_data(show_spinner=False)
def _load(source: str, db_version: int) -> pd.DataFrame:
    return load_player_games(source=source, db_path=DEFAULT_DB_PATH)


try:
    if source == "real" and not DEFAULT_DB_PATH.exists():
        states.empty_state(
            "Nenhum dado real encontrado ainda",
            "Colete jogos reais antes de usar esta fonte.",
            actions=[("Coletar dados", "rode 'python scripts/update_data.py' no terminal do projeto")],
        )
    player_games = _load(source, db_version)
except (ValueError, FileNotFoundError) as error:
    states.error_state("Não foi possível carregar os dados de jogadores.", detail=str(error))
    st.stop()

components.source_badge(
    "Base demonstrativa" if source == "demo" else "Dados reais (coletados)",
    None if source == "demo" else components.db_last_updated(DEFAULT_DB_PATH),
)
if source == "demo":
    components.note("Os jogadores e estatísticas desta tela são sintéticos e não representam atletas reais.")

players = list_players(player_games)
summary = player_season_summary(player_games)
player_index = build_player_index(player_games)
player_options = (players["player_name"] + " (" + players["team"] + ")").tolist()
player_id_by_label = dict(zip(player_options, players["player_id"], strict=True))

requested_id = st.query_params.get("player_id")
if requested_id:
    requested = players[players["player_id"].astype(str).eq(requested_id)]
    if not requested.empty:
        athlete = requested.iloc[0]
        st.query_params["player"] = f"{athlete['player_name']} ({athlete['team']})"
    del st.query_params["player_id"]


@st.cache_data(show_spinner=False)
def _load_team_games(source: str, db_version: int) -> pd.DataFrame:
    return load_real_games(DEFAULT_DB_PATH) if source == "real" else generate_demo_games()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_nba_schedule(
    retry_token: int = 0, team_tricode: str | None = None
) -> tuple[pd.DataFrame, str | None]:
    """Cache schedule for one hour by team; a changed token forces a fresh lookup."""
    _ = retry_token  # Included in the cache key so the refresh button bypasses a stale result.
    try:
        return fetch_nba_schedule(team_tricode=team_tricode), None
    except RuntimeError as error:
        return pd.DataFrame(), str(error)


try:
    team_games = _load_team_games(source, db_version)
except (ValueError, FileNotFoundError):
    team_games = None


@st.cache_resource(show_spinner=False)
def _train_projection_bundle(player_games: pd.DataFrame, team_games: pd.DataFrame):
    features = add_rolling_features(player_games)
    if team_games is not None:
        features = add_opponent_context(features, team_games)
    else:
        features["opponent_def_rating"] = 113.0  # neutro, sem base de times disponível
    return train_player_models(features)


tab_labels = ["Visão geral", "Perfil individual", "Comparação", "Projeções"]
if st.query_params.get("view") == "profile":
    tab_labels[:2] = ["Perfil individual", "Visão geral"]
tab_by_label = dict(zip(tab_labels, st.tabs(tab_labels), strict=True))
tab_overview, tab_profile, tab_compare, tab_projection = (
    tab_by_label[label] for label in ("Visão geral", "Perfil individual", "Comparação", "Projeções")
)

with tab_overview:
    players_tabs.overview_tab(player_index, players, source, summary)

with tab_profile:
    players_tabs.profile_tab(player_games, player_id_by_label, player_index, player_options, source)

with tab_compare:
    players_tabs.compare_tab(player_games, player_id_by_label, player_options, source)

with tab_projection:
    players_projection.projection_tab(
        _load_nba_schedule,
        _train_projection_bundle,
        player_games,
        player_id_by_label,
        player_options,
        players,
        source,
        team_games,
    )
