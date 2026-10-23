from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from src.daily_games import (
    build_form_table,
    format_tipoff,
    game_headliner,
    games_for_date,
    status_label,
    team_highlights,
    today_et,
)
from src.data import load_real_games, team_snapshot
from src.nba_schedule import fetch_nba_schedule
from src.player_data import load_player_games
from src.player_features import add_opponent_context, add_rolling_features
from src.player_metrics import player_snapshot
from src.player_model import predict_player_game, train_player_models
from src.store import DEFAULT_DB_PATH, count_player_games
from src.ui import components, states, theme
from src.ui.formatters import format_date_br

st.set_page_config(
    page_title="Jogos do Dia — NBA Analytics Lab",
    page_icon="📅",
    layout="wide",
)

theme.inject_base_style()

st.markdown("## 📅 Jogos do Dia")
st.caption(
    "Todos os confrontos do dia e os jogadores em destaque de cada partida, pela forma "
    "recente. Estimativas educacionais, não orientação de apostas."
)

with st.sidebar:
    st.header("Configuração")
    top_n = st.slider("Destaques por time", 1, 6, 3)
    show_projection = st.checkbox(
        "Incluir projeção do modelo",
        value=False,
        help="Treina o modelo de jogadores na primeira vez (pode demorar) e projeta "
        "minutos, pontos, rebotes e assistências de cada destaque.",
    )
    if st.button("Atualizar calendário"):
        st.session_state["daily_schedule_retry"] = int(st.session_state.get("daily_schedule_retry", 0)) + 1
    st.divider()
    st.caption(
        "Este projeto produz estimativas esportivas educacionais. "
        "Não utiliza odds e não fornece orientação de apostas."
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _load_schedule(retry_token: int) -> tuple[pd.DataFrame, str | None]:
    _ = retry_token  # entra na chave do cache para o botão "Atualizar" forçar nova consulta
    try:
        return fetch_nba_schedule(lookahead_days=7), None
    except RuntimeError as error:
        return pd.DataFrame(), str(error)


@st.cache_resource(show_spinner=False)
def _load_player_games(db_path: str, updated_at: float) -> pd.DataFrame:
    _ = updated_at  # invalida o cache quando o banco é atualizado
    return load_player_games(source="real", db_path=db_path)


@st.cache_resource(show_spinner=False)
def _form_table(db_path: str, updated_at: float) -> pd.DataFrame:
    return build_form_table(_load_player_games(db_path, updated_at))


@st.cache_resource(show_spinner="Treinando o modelo de jogadores...")
def _model_context(db_path: str, updated_at: float):
    player_games = _load_player_games(db_path, updated_at)
    try:
        team_games = load_real_games(db_path)
    except (ValueError, FileNotFoundError):
        team_games = None
    features = add_rolling_features(player_games)
    if team_games is not None:
        features = add_opponent_context(features, team_games)
    else:
        features["opponent_def_rating"] = 113.0
    return train_player_models(features), player_games, team_games


@st.cache_data(show_spinner=False)
def _project_player(
    db_path: str,
    updated_at: float,
    player_id: int,
    opponent_name: str,
    is_home: bool,
    rest_days: int,
) -> dict | None:
    bundle, player_games, team_games = _model_context(db_path, updated_at)
    opponent_def_rating = None
    if team_games is not None:
        try:
            opponent_def_rating = team_snapshot(team_games, opponent_name)["def_rating"]
        except (ValueError, KeyError):
            opponent_def_rating = None
    try:
        snapshot = player_snapshot(player_games, player_id)
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
    }


db_path = str(DEFAULT_DB_PATH)
player_data_available = DEFAULT_DB_PATH.exists() and count_player_games(DEFAULT_DB_PATH) > 0
updated_at = DEFAULT_DB_PATH.stat().st_mtime if DEFAULT_DB_PATH.exists() else 0.0

today = today_et()
selected_day = st.date_input(
    "Data dos jogos (data do calendário da NBA, fuso da costa leste dos EUA)",
    value=today,
    min_value=today - timedelta(days=7),
    max_value=today + timedelta(days=30),
)

schedule, schedule_error = _load_schedule(int(st.session_state.get("daily_schedule_retry", 0)))
games = games_for_date(schedule, selected_day)

if schedule_error:
    states.error_state(
        "Não foi possível consultar o calendário da NBA agora.",
        detail=f"{schedule_error} Use 'Atualizar calendário' na barra lateral para tentar de novo.",
    )
    st.stop()

if games.empty:
    st.info(
        f"Nenhum jogo encontrado para {format_date_br(selected_day)}. "
        "Tente outra data — o calendário alternativo (ESPN) cobre só os próximos dias."
    )
    st.stop()

source_name = str(games["schedule_source"].iloc[0]) if "schedule_source" in games.columns else "NBA"
components.source_badge(
    f"Calendário — {source_name}",
    components.db_last_updated(DEFAULT_DB_PATH) if player_data_available else None,
)
st.markdown(f"#### {len(games)} jogo(s) em {format_date_br(selected_day)}")

if player_data_available:
    form_table = _form_table(db_path, updated_at)
    states.stale_data_notice(components.db_last_updated(DEFAULT_DB_PATH), days_threshold=3)
else:
    form_table = pd.DataFrame()
    components.note(
        "Sem estatísticas de jogadores coletadas: mostrando só o calendário. Colete dados em "
        "'Dados e Atualizações' para ver os destaques.",
        kind="warning",
    )


def _highlight_table(team_players: pd.DataFrame, opponent_name: str, is_home: bool) -> pd.DataFrame:
    table = pd.DataFrame(
        {
            "Jogador": team_players["player_name"],
            "Destaque": team_players["tag"],
            "Min": team_players["minutes_recent"],
            "PTS": team_players["pts_recent"],
            "REB": team_players["reb_recent"],
            "AST": team_players["ast_recent"],
            "PTS vs. temporada": team_players["pts_delta"],
        }
    )
    if show_projection:
        projections = []
        for row in team_players.itertuples():
            rest_days = min(7, max(0, (selected_day - row.last_game_date.date()).days - 1))
            projections.append(
                _project_player(
                    db_path, updated_at, int(row.player_id), opponent_name, is_home, rest_days
                )
            )
        for key, label in (("pts", "Proj. PTS"), ("reb", "Proj. REB"), ("ast", "Proj. AST")):
            table[label] = [p[key] if p else float("nan") for p in projections]
        table["Confiança"] = [p["confidence"] if p else "—" for p in projections]
    return table


for _, game in games.iterrows():
    away_name, home_name = str(game["away_team_name"]), str(game["home_team_name"])
    with st.container(border=True):
        st.markdown(f"### {away_name} @ {home_name}")
        details = [format_tipoff(game.get("game_datetime_utc")), status_label(game.get("game_status"))]
        if str(game.get("arena_name") or "").strip():
            details.append(str(game["arena_name"]))
        st.caption(" · ".join(details))

        if form_table.empty:
            continue

        away_players = team_highlights(form_table, str(game["away_team_tricode"]), top_n=top_n)
        home_players = team_highlights(form_table, str(game["home_team_tricode"]), top_n=top_n)

        headliner = game_headliner(home_players, away_players)
        if headliner is not None:
            st.markdown(
                f"⭐ **Destaque da partida:** {headliner['player_name']} — "
                f"{headliner['pts_recent']:.1f} pts, {headliner['reb_recent']:.1f} reb, "
                f"{headliner['ast_recent']:.1f} ast nos últimos jogos"
            )

        for column, team_name, team_players, opponent, is_home in (
            *zip(
                st.columns(2),
                (away_name, home_name),
                (away_players, home_players),
                (home_name, away_name),
                (False, True),
                strict=True,
            ),
        ):
            with column:
                st.markdown(f"**{team_name}**")
                if team_players.empty:
                    st.caption("Sem jogadores elegíveis na base (histórico ou minutos insuficientes).")
                    continue
                table = _highlight_table(team_players, opponent, is_home)
                formats = {
                    "Min": "{:.1f}",
                    "PTS": "{:.1f}",
                    "REB": "{:.1f}",
                    "AST": "{:.1f}",
                    "PTS vs. temporada": "{:+.1f}",
                    "Proj. PTS": "{:.1f}",
                    "Proj. REB": "{:.1f}",
                    "Proj. AST": "{:.1f}",
                }
                st.dataframe(
                    table.style.format(
                        {key: value for key, value in formats.items() if key in table.columns},
                        na_rep="—",
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

if not form_table.empty:
    st.caption(
        "Destaques: ranking pelo índice de impacto recente (pontos + 0,7 × rebotes + assistências, "
        "média dos últimos 5 jogos com minutos). 'PTS vs. temporada' compara a forma recente com a "
        "média da temporada mais recente do jogador. A base não tem dados de lesão ou escalação "
        "confirmada: um destaque pode estar fora da partida — confira o status oficial antes de "
        "interpretar. Horários em Brasília e na costa leste (ET)."
    )
