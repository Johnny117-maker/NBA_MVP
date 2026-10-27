from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from src.current_roster import fetch_current_roster
from src.daily_games import (
    EASTERN,
    build_form_table,
    format_tipoff,
    game_headliner,
    games_for_date,
    status_label,
    team_highlights,
    team_rest_days,
    today_et,
)
from src.data import load_real_games, team_snapshot
from src.model import predict_game, train_models
from src.nba_schedule import SCHEDULE_COLUMNS, fetch_nba_schedule
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
from src.player_data import load_player_games
from src.player_features import add_opponent_context, add_rolling_features
from src.player_metrics import player_snapshot
from src.player_model import predict_player_game, train_player_models
from src.schedule_storage import DEFAULT_SCHEDULE_CACHE_PATH, read_schedule_cache, save_schedule_cache
from src.store import DEFAULT_DB_PATH, count_player_games
from src.ui import components, states, theme
from src.ui.formatters import format_date_br
from src.ui.insights import matchup_intel

st.set_page_config(
    page_title="Jogos do Dia — NBA Analytics Lab",
    page_icon="📅",
    layout="wide",
)

theme.inject_base_style("games")

components.page_header(
    "Sua visão da rodada.",
    "Explore os confrontos do dia, veja os destaques de cada equipe e aprofunde a análise da partida.",
    category="JOGOS DO DIA",
)

with st.expander("Opções da rodada", expanded=False):
    st.subheader("Preferências da rodada")
    top_n = st.slider("Destaques por time", 1, 6, 3)
    show_projection = st.checkbox(
        "Incluir projeção do modelo",
        value=False,
        help="Treina o modelo de jogadores na primeira vez (pode demorar) e projeta "
        "minutos, pontos, rebotes e assistências de cada destaque.",
    )
    if st.button("Atualizar calendário"):
        st.session_state["daily_schedule_retry"] = int(st.session_state.get("daily_schedule_retry", 0)) + 1


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_schedule(retry_token: int, selected_day: date) -> pd.DataFrame:
    _ = retry_token  # entra na chave do cache para o botão "Atualizar" forçar nova consulta
    schedule = fetch_nba_schedule(lookahead_days=1, start_date=selected_day)
    try:
        save_schedule_cache(schedule, DEFAULT_SCHEDULE_CACHE_PATH)
    except OSError:
        logging.getLogger(__name__).warning("Não foi possível salvar uma cópia local do calendário.")
    return schedule


def _load_schedule(retry_token: int, selected_day: date) -> tuple[pd.DataFrame, str | None]:
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


def _manual_schedule(selected_day: date) -> pd.DataFrame:
    """Permite continuar a análise sem apresentar um confronto manual como oficial."""
    with st.expander("Informar confronto manualmente", expanded=True):
        st.caption(
            "Se você souber o confronto, informe os times e o horário para analisar a partida. "
            "Esses dados ficam nesta sessão e serão identificados como cadastro manual."
        )
        codes = sorted(TEAM_ABBREVIATION_TO_NAME, key=TEAM_ABBREVIATION_TO_NAME.__getitem__)
        with st.form("manual_daily_game"):
            home = st.selectbox("Time mandante", codes, format_func=TEAM_ABBREVIATION_TO_NAME.__getitem__)
            away = st.selectbox(
                "Time visitante",
                codes,
                index=1,
                format_func=TEAM_ABBREVIATION_TO_NAME.__getitem__,
            )
            tipoff = st.time_input("Horário na costa leste dos EUA (ET)", value=time(19, 0))
            submitted = st.form_submit_button("Analisar confronto")
        if submitted:
            if home == away:
                st.error("Escolha dois times diferentes.")
            else:
                game_id = f"manual-{selected_day.isoformat()}-{home}-{away}"
                records = st.session_state.get("manual_daily_games", {})
                records[game_id] = {
                    "game_id": game_id,
                    "game_date": pd.Timestamp(selected_day),
                    "game_datetime_utc": pd.Timestamp(
                        datetime.combine(selected_day, tipoff, tzinfo=EASTERN).astimezone(UTC)
                    ),
                    "game_status": 1,
                    "home_team_tricode": home,
                    "home_team_name": TEAM_ABBREVIATION_TO_NAME[home],
                    "away_team_tricode": away,
                    "away_team_name": TEAM_ABBREVIATION_TO_NAME[away],
                    "arena_name": "",
                    "schedule_source": "Cadastro manual",
                }
                st.session_state["manual_daily_games"] = records
    records = list(st.session_state.get("manual_daily_games", {}).values())
    return pd.DataFrame(records, columns=SCHEDULE_COLUMNS)


@st.cache_resource(show_spinner=False)
def _load_player_games(db_path: str, updated_at: float, selected_day: date) -> pd.DataFrame:
    _ = updated_at  # invalida o cache quando o banco é atualizado
    games = load_player_games(source="real", db_path=db_path)
    return games.loc[pd.to_datetime(games["game_date"]).dt.date < selected_day].copy()


@st.cache_data(show_spinner=False)
def _load_team_games(db_path: str, updated_at: float, selected_day: date) -> pd.DataFrame:
    _ = updated_at
    games = load_real_games(db_path)
    return games.loc[pd.to_datetime(games["game_date"]).dt.date < selected_day].copy()


@st.cache_resource(show_spinner="Treinando o modelo de times...")
def _team_model_context(db_path: str, updated_at: float, selected_day: date):
    games = _load_team_games(db_path, updated_at, selected_day)
    return train_models(games), games


@st.cache_data(ttl=21600, show_spinner=False)
def _load_current_roster() -> pd.DataFrame:
    return fetch_current_roster()


@st.cache_data(show_spinner=False)
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


@st.cache_resource(show_spinner="Treinando o modelo de jogadores...")
def _model_context(db_path: str, updated_at: float, selected_day: date):
    player_games = _load_player_games(db_path, updated_at, selected_day)
    try:
        team_games = _load_team_games(db_path, updated_at, selected_day)
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
    selected_day: date,
) -> dict | None:
    bundle, player_games, team_games = _model_context(db_path, updated_at, selected_day)
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


def _choose_day(day: date) -> None:
    st.session_state["daily_selected_day"] = day


with st.container(key="daily_date_controls"):
    date_column, shortcuts = st.columns([2, 1])
    with date_column:
        selected_day = st.date_input(
            "Data dos jogos · calendário da costa leste (ET)",
            value=today,
            min_value=today - timedelta(days=7),
            max_value=today + timedelta(days=30),
            key="daily_selected_day",
            format="DD/MM/YYYY",
        )
    with shortcuts:
        st.caption("Navegação rápida")
        for column, label, offset in zip(st.columns(3), ("Ontem", "Hoje", "Amanhã"), (-1, 0, 1), strict=True):
            column.button(
                label, key=f"day_{offset}", on_click=_choose_day, args=(today + timedelta(days=offset),)
            )

schedule, schedule_error = _load_schedule(int(st.session_state.get("daily_schedule_retry", 0)), selected_day)
games = games_for_date(schedule, selected_day)

if schedule_error:
    st.warning(
        "NBA e ESPN não responderam, e o arquivo público SportsDataverse também está indisponível. "
        "Use 'Atualizar calendário' para tentar novamente ou informe um confronto abaixo."
    )
    with st.expander("Detalhes da consulta"):
        st.write(schedule_error)
    if not games.empty:
        st.info(
            "Exibindo uma cópia do calendário salva anteriormente. "
            "Horários e status podem ter mudado; os resultados ao vivo estão indisponíveis."
        )

if games.empty:
    st.info(
        f"Nenhum jogo encontrado para {format_date_br(selected_day)}. "
        "Você pode escolher outra data ou informar um confronto manualmente."
    )
if schedule_error or games.empty:
    manual = games_for_date(_manual_schedule(selected_day), selected_day)
    if not manual.empty:
        games = manual if games.empty else pd.concat([games, manual], ignore_index=True)
        games = games.drop_duplicates(["game_date", "home_team_tricode", "away_team_tricode"], keep="last")
if games.empty:
    st.stop()

search = st.text_input(
    "Buscar time na rodada", placeholder="Ex.: Celtics, Lakers ou Knicks", key="daily_team_search"
)
if search.strip():
    query = search.strip()
    games = games[
        games["home_team_name"].str.contains(query, case=False, regex=False)
        | games["away_team_name"].str.contains(query, case=False, regex=False)
    ]
    if games.empty:
        st.info("Nenhum confronto corresponde à busca. Tente outro nome de time ou limpe o campo.")
        st.stop()

source_name = ", ".join(games["schedule_source"].dropna().astype(str).unique())
public_snapshot = games["schedule_source"].fillna("").str.startswith("SportsDataverse").any()
components.source_badge(
    f"Calendário — {source_name}",
    components.db_last_updated(DEFAULT_SCHEDULE_CACHE_PATH),
)
components.section_header(
    f"{len(games)} jogo(s) em {format_date_br(selected_day)}",
    "Horários em Brasília e ET. Abra os destaques de cada confronto para consultar os jogadores.",
)

if public_snapshot:
    with st.expander("Fonte e atualização do calendário", expanded=False):
        st.caption(
            "Calendário gratuito com atualização periódica; status e horários podem ter atraso. "
            "Elenco atual não confirmado: os destaques usam as equipes do histórico local."
        )
        st.markdown(
            "Dados: [SportsDataverse / hoopR](https://github.com/sportsdataverse/hoopR-nba-data) "
            "([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). "
            "Datas e equipes normalizadas para esta aplicação."
        )

if player_data_available:
    current_roster = pd.DataFrame()
    roster_records: tuple[tuple[int, str], ...] = ()
    roster_version = "historical-fallback"

    try:
        if selected_day >= today and not schedule_error and not public_snapshot:
            current_roster = _load_current_roster()

        if not current_roster.empty:
            roster_records = tuple(
                (int(row.player_id), str(row.team).strip().upper())
                for row in current_roster.itertuples(index=False)
                if str(row.team).strip()
            )
            roster_version = str(hash(roster_records))

    except Exception as exc:
        st.warning(
            "Não foi possível consultar o elenco atual da NBA. "
            "Os destaques usarão os times registrados no histórico. "
            f"Detalhe: {exc}"
        )

    form_table = _form_table(
        db_path,
        updated_at,
        roster_version,
        roster_records,
        selected_day,
    )
    states.stale_data_notice(
        components.db_last_updated(DEFAULT_DB_PATH),
        days_threshold=3,
    )
else:
    form_table = pd.DataFrame()
    components.note(
        "Sem estatísticas de jogadores coletadas: calendário e probabilidades dos times "
        "continuam disponíveis quando há histórico suficiente. Colete dados em "
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
            # O treinamento usa a diferença entre datas: back-to-back = 1.
            rest_days = min(7, max(1, (selected_day - row.last_game_date.date()).days))
            projections.append(
                _project_player(
                    db_path, updated_at, int(row.player_id), opponent_name, is_home, rest_days, selected_day
                )
            )
        for key, label in (("pts", "Proj. PTS"), ("reb", "Proj. REB"), ("ast", "Proj. AST")):
            table[label] = [p[key] if p else float("nan") for p in projections]
        table["Confiança"] = [p["confidence"] if p else "—" for p in projections]
    return table


try:
    team_bundle, team_games = _team_model_context(db_path, updated_at, selected_day)
except (ValueError, FileNotFoundError, KeyError):
    team_bundle, team_games = None, pd.DataFrame()
    st.info("Probabilidades indisponíveis: colete histórico suficiente de jogos dos times.")

if team_bundle is not None:
    st.caption(
        "Probabilidades experimentais pelo modelo de Times, considerando histórico e descanso das equipes."
    )

tab_round, tab_matchup = st.tabs(["Rodada", "Central da partida"])

with tab_round:
    for _, game in games.iterrows():
        away_name, home_name = str(game["away_team_name"]), str(game["home_team_name"])
        with st.container(border=True):
            st.markdown(f"### {away_name} @ {home_name}")
            details = [format_tipoff(game.get("game_datetime_utc")), status_label(game.get("game_status"))]
            if str(game.get("arena_name") or "").strip():
                details.append(str(game["arena_name"]))
            st.caption(" · ".join(details))

            if team_bundle is not None:
                try:
                    away_snapshot = team_snapshot(team_games, away_name)
                    home_snapshot = team_snapshot(team_games, home_name)
                    prediction = predict_game(
                        team_bundle,
                        home_snapshot,
                        away_snapshot,
                        team_rest_days(team_games, home_name, selected_day),
                        team_rest_days(team_games, away_name, selected_day),
                    )
                    prob_cols = st.columns(2)
                    prob_cols[0].metric(f"Prob. {away_name}", f"{prediction.away_win_probability:.0%}")
                    prob_cols[1].metric(f"Prob. {home_name}", f"{prediction.home_win_probability:.0%}")
                except (ValueError, KeyError, TypeError, OverflowError):
                    st.info("Probabilidade indisponível: histórico recente insuficiente para um dos times.")

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

            with st.expander("Ver destaques das equipes", expanded=False):
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
                            st.caption(
                                "Sem jogadores elegíveis na base (histórico ou minutos insuficientes)."
                            )
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

with tab_matchup:
    if not team_games.empty:
        components.section_header(
            "Central da partida", "Escolha um confronto da rodada para explorar as equipes."
        )
        matchups = games.reset_index(drop=True)
        selected_matchup = st.selectbox(
            "Detalhar confronto", list(range(len(matchups))),
            format_func=lambda idx: (
                f"{matchups.iloc[idx]['away_team_name']} @ {matchups.iloc[idx]['home_team_name']}"
            ),
            key="daily_matchup_detail",
        )
        chosen = matchups.iloc[selected_matchup]
        matchup_intel(team_games, str(chosen["away_team_name"]), str(chosen["home_team_name"]), key="daily")

    else:
        st.info("Colete histórico de times para abrir a central da partida.")
