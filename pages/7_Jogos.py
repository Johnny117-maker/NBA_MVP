from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from src.daily_games import (
    EASTERN,
    format_tipoff,
    game_headliner,
    games_for_date,
    status_label,
    team_highlights,
    team_rest_days,
    today_et,
)
from src.data import team_snapshot
from src.live_providers import team_code
from src.model import predict_game
from src.nba_schedule import SCHEDULE_COLUMNS
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
from src.round_context import (
    _form_table,
    _load_current_roster,
    _load_schedule,
    _project_player,
    _team_model_context,
)
from src.schedule_storage import DEFAULT_SCHEDULE_CACHE_PATH
from src.store import DEFAULT_DB_PATH, count_player_games
from src.today_picks import round_highlights
from src.ui import components, theme
from src.ui.archive import archived_preview
from src.ui.formatters import format_date_br
from src.ui.injuries import annotate_injuries, injury_notice
from src.ui.insights import matchup_intel
from src.ui.navigation import page_link
from src.ui.round_cards import highlights_grid, history_notice

st.set_page_config(
    page_title="Jogos do Dia — NBA Analytics Lab",
    page_icon="📅",
    layout="wide",
)

theme.inject_base_style("games")

components.page_header(
    "Sua visão da rodada.",
    "Os protagonistas primeiro. Descubra quem acompanhar e explore cada confronto da rodada.",
    category="JOGOS DO DIA",
)
injury_notice(DEFAULT_DB_PATH)
page_link("match_center", "Abrir a central de uma partida")


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


db_path = str(DEFAULT_DB_PATH)
player_data_available = DEFAULT_DB_PATH.exists() and count_player_games(DEFAULT_DB_PATH) > 0
updated_at = DEFAULT_DB_PATH.stat().st_mtime if DEFAULT_DB_PATH.exists() else 0.0

today = today_et()


def _choose_day(day: date) -> None:
    st.session_state["daily_selected_day"] = day


def _refresh_schedule() -> None:
    st.session_state["daily_schedule_retry"] = int(st.session_state.get("daily_schedule_retry", 0)) + 1


with st.container(key="daily_date_controls"):
    date_column, team_search_column, shortcuts, settings_column = st.columns([1.5, 1.7, 1.5, 0.8])
    with date_column:
        selected_day = st.date_input(
            "Data da rodada (ET)",
            value=today,
            min_value=today - timedelta(days=7),
            max_value=today + timedelta(days=30),
            key="daily_selected_day",
            format="DD/MM/YYYY",
        )
    with team_search_column:
        search = st.text_input(
            "Buscar time na rodada", placeholder="Ex.: Celtics, Lakers ou Knicks", key="daily_team_search"
        )
    with shortcuts:
        st.caption("Navegação rápida")
        for column, label, offset in zip(st.columns(3), ("Ontem", "Hoje", "Amanhã"), (-1, 0, 1), strict=True):
            column.button(
                label, key=f"day_{offset}", on_click=_choose_day, args=(today + timedelta(days=offset),)
            )

    with settings_column:
        st.caption("Preferências")
        settings_popup = st.popover("Ajustes")
        with settings_popup:
            st.subheader("Preferências da rodada")
            top_n = st.slider("Destaques por time", 1, 6, 3)
            show_projection = st.checkbox(
                "Incluir projeção do modelo",
                value=False,
                help="Treina o modelo de jogadores na primeira vez (pode demorar) e projeta "
                "minutos, pontos, rebotes e assistências de cada destaque.",
            )
            st.button("Atualizar calendário", on_click=_refresh_schedule)

archived_preview(DEFAULT_DB_PATH, selected_day.isoformat(), "games_archive")
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

if search.strip():
    query = search.strip()
    games = games[
        games["home_team_name"].str.contains(query, case=False, regex=False)
        | games["away_team_name"].str.contains(query, case=False, regex=False)
        | games["home_team_tricode"].str.contains(query, case=False, regex=False)
        | games["away_team_tricode"].str.contains(query, case=False, regex=False)
    ]
    if games.empty:
        st.info("Nenhum confronto corresponde à busca. Tente outro nome de time ou limpe o campo.")
        st.stop()

source_name = ", ".join(games["schedule_source"].dropna().astype(str).unique())
public_snapshot = games["schedule_source"].fillna("").str.startswith("SportsDataverse").any()
summary_column, picks_link = st.columns([3, 1])
with summary_column:
    components.section_header(f"{len(games)} jogo(s) em {format_date_br(selected_day)}")
with picks_link:
    page_link("picks", "Ver palpites de hoje")

with settings_popup, st.expander("Fonte e atualização do calendário", expanded=False):
    components.source_badge(
        f"Calendário — {source_name}",
        components.db_last_updated(DEFAULT_SCHEDULE_CACHE_PATH),
    )
    if public_snapshot:
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
    history_notice(form_table, selected_day)
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
            try:
                projections.append(
                    _project_player(
                        db_path,
                        updated_at,
                        int(row.player_id),
                        opponent_name,
                        is_home,
                        rest_days,
                        selected_day,
                    )
                )
            except MemoryError:
                st.error(
                    "Memória insuficiente para projetar jogadores nesta sessão. "
                    "Desmarque a projeção em Ajustes para continuar consultando os destaques."
                )
                st.stop()
        for key, label in (("pts", "Proj. PTS"), ("reb", "Proj. REB"), ("ast", "Proj. AST")):
            table[label] = [p[key] if p else float("nan") for p in projections]
        table["Confiança"] = [p["confidence"] if p else "—" for p in projections]
    return table


try:
    team_bundle, team_games = _team_model_context(db_path, updated_at, selected_day)
except (ValueError, FileNotFoundError, KeyError):
    team_bundle, team_games = None, pd.DataFrame()
    st.info("Probabilidades indisponíveis: colete histórico suficiente de jogos dos times.")

tab_stars, tab_round, tab_matchup = st.tabs(["Jogadores de destaque", "Confrontos", "Central da partida"])

with tab_stars:
    candidates = round_highlights(form_table, games, top_n=top_n)
    if candidates.empty:
        st.info("Nenhum jogador elegível nestes confrontos. Colete estatísticas em Dados e atualizações.")
    else:
        search_column, order_column, role_column, limit_column = st.columns([2, 1, 1, 0.6])
        with search_column:
            athlete_search = st.text_input("Buscar jogador de destaque", placeholder="Nome do atleta…")
        with order_column:
            order_options = {
                "Impacto recente": "impact_recent",
                "Pontos": "pts_recent",
                "Rebotes": "reb_recent",
                "Assistências": "ast_recent",
            }
            order = st.selectbox("Ordenar destaques", list(order_options))
        with role_column:
            role = st.selectbox(
                "Perfil em destaque", ["Todos", "Em alta", "Cestinha", "Reboteiro", "Criador"]
            )
        if athlete_search.strip():
            candidates = candidates[
                candidates["player_name"].str.contains(
                    athlete_search.strip(),
                    case=False,
                    regex=False,
                )
            ]
        if role != "Todos":
            candidates = candidates[candidates["tag"].str.contains(role, regex=False)]
        candidates = candidates.sort_values(order_options[order], ascending=False)
        with limit_column:
            visible = st.selectbox("Exibir", ["6", "12", "Todos"])
        shown = candidates if visible == "Todos" else candidates.head(int(visible))
        st.caption(
            f"Exibindo {len(shown)} de {len(candidates)} atletas · histórico anterior à data da rodada."
        )
        if shown.empty:
            st.info("Nenhum destaque corresponde aos filtros. Tente outro nome ou perfil.")
        else:
            highlights_grid(shown)
        with st.expander("Como escolhemos os destaques"):
            st.caption(
                "Impacto = pontos + 0,7 × rebotes + assistências, nas últimas até cinco partidas da "
                "temporada mais recente de cada atleta. São elegíveis jogadores com média de pelo menos "
                "10 minutos e última atuação a até 45 dias da partida mais recente da base. "
                "Em alta: pelo menos três pontos acima da média da temporada."
            )

with tab_round:
    if team_bundle is not None:
        st.caption("Probabilidades experimentais pelo modelo de Times, considerando histórico e descanso.")
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
                        if selected_day >= today_et():
                            table = annotate_injuries(table, DEFAULT_DB_PATH, team_code(team_name))
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
                            width="stretch",
                        )

    if not form_table.empty:
        st.caption(
            "Destaques: ranking pelo índice de impacto recente (pontos + 0,7 × rebotes + assistências, "
            "média dos últimos 5 jogos com minutos). 'PTS vs. temporada' compara a forma recente com a "
            "média da temporada mais recente do jogador. O boletim de lesões é uma consulta separada; "
            "ausência de registro não confirma participação, e um destaque pode estar fora. "
            "Horários em Brasília e na costa leste (ET)."
        )

with tab_matchup:
    if not team_games.empty:
        components.section_header(
            "Central da partida", "Escolha um confronto da rodada para explorar as equipes."
        )
        matchups = games.reset_index(drop=True)
        selected_matchup = st.selectbox(
            "Detalhar confronto",
            list(range(len(matchups))),
            format_func=lambda idx: (
                f"{matchups.iloc[idx]['away_team_name']} @ {matchups.iloc[idx]['home_team_name']}"
            ),
            key="daily_matchup_detail",
        )
        chosen = matchups.iloc[selected_matchup]
        matchup_intel(team_games, str(chosen["away_team_name"]), str(chosen["home_team_name"]), key="daily")

    else:
        st.info("Colete histórico de times para abrir a central da partida.")
