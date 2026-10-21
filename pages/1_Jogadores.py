from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.data import available_teams, generate_demo_games, load_real_games, team_snapshot
from src.player_data import load_player_games
from src.nba_schedule import fetch_nba_schedule, get_next_game_for_team
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
from src.player_features import (
    add_opponent_context,
    add_rolling_features,
    assign_team_stints,
    season_start_year,
)
from src.player_index import DIMENSION_LABELS, build_player_index
from src.player_metrics import compare_players, list_players, player_season_summary, player_snapshot
from src.player_model import (
    over_probability,
    predict_player_game,
    range_probabilities,
    train_player_models,
)
from src.store import DEFAULT_DB_PATH, count_player_games, log_player_prediction
from src.ui import components, states, theme

st.set_page_config(
    page_title="Jogadores — NBA Analytics Lab",
    page_icon="🧮",
    layout="wide",
)

theme.inject_base_style()

st.markdown("## 🧮 Jogadores")
st.caption(
    "Produção, eficiência (TS%, eFG%, USG%, AST/TO), estatísticas por 36 minutos "
    "e consistência por jogador. Estimativas educacionais, não orientação de apostas."
)

real_data_available = DEFAULT_DB_PATH.exists() and count_player_games(DEFAULT_DB_PATH) > 0

with st.sidebar:
    st.header("Configuração")
    source_label = st.radio(
        "Fonte dos dados",
        ["Base demonstrativa", "Dados reais (coletados)"],
        index=1 if real_data_available else 0,
        help=(
            "A base demonstrativa é sintética. Dados reais exigem rodar "
            "'python scripts/update_data.py' antes."
        ),
    )
    st.divider()
    st.caption(
        "Este projeto produz estimativas esportivas educacionais. "
        "Não utiliza odds e não fornece orientação de apostas."
    )

source = "demo" if source_label == "Base demonstrativa" else "real"


@st.cache_data(show_spinner=False)
def _load(source: str) -> pd.DataFrame:
    return load_player_games(source=source)


try:
    if source == "real" and not DEFAULT_DB_PATH.exists():
        states.empty_state(
            "Nenhum dado real encontrado ainda",
            "Colete jogos reais antes de usar esta fonte.",
            actions=[
                ("Coletar dados", "rode 'python scripts/update_data.py' no terminal do projeto")
            ],
        )
    player_games = _load(source)
except (ValueError, FileNotFoundError) as error:
    states.error_state("Não foi possível carregar os dados de jogadores.", detail=str(error))
    st.stop()

components.source_badge(
    "Base demonstrativa" if source == "demo" else "Dados reais (coletados)",
    None if source == "demo" else components.db_last_updated(DEFAULT_DB_PATH),
)
if source == "demo":
    components.note(
        "Os jogadores e estatísticas desta tela são sintéticos e não representam atletas reais."
    )

players = list_players(player_games)
summary = player_season_summary(player_games)
player_index = build_player_index(player_games)
player_options = (players["player_name"] + " (" + players["team"] + ")").tolist()
player_id_by_label = dict(zip(player_options, players["player_id"], strict=True))


@st.cache_data(show_spinner=False)
def _load_team_games(source: str) -> pd.DataFrame:
    return load_real_games() if source == "real" else generate_demo_games()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_nba_schedule(retry_token: int = 0) -> tuple[pd.DataFrame, str | None]:
    """Cache schedule for one hour; a changed token forces a fresh lookup."""
    _ = retry_token  # Included in the cache key so the refresh button bypasses a stale result.
    try:
        return fetch_nba_schedule(), None
    except RuntimeError as error:
        return pd.DataFrame(), str(error)


try:
    team_games = _load_team_games(source)
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


tab_overview, tab_profile, tab_compare, tab_projection = st.tabs(
    ["Visão geral", "Perfil individual", "Comparação", "Projeções"]
)

with tab_overview:
    st.caption(
        "NAPS é um índice experimental do projeto (0-100, por percentil entre jogadores "
        "qualificados) — não é uma medida oficial nem absoluta de qualidade. "
        "Veja a seção 'Página de jogadores' do README para os pesos e limitações."
    )
    teams = ["Todos"] + sorted(players["team"].unique())
    team_filter = st.selectbox(
        "Filtrar por time", teams, index=0, key=f"team_filter_{source}"
    )

    ranking = summary.merge(
        player_index[["player_id", "naps", "style"]], on="player_id", how="left"
    )
    ranking = ranking if team_filter == "Todos" else ranking[ranking["team"] == team_filter]
    ranking = ranking.sort_values("naps", ascending=False, na_position="last")

    display_columns = {
        "player_name": "Jogador",
        "team": "Time",
        "games": "Jogos",
        "minutes_mean": "Minutos",
        "pts_mean": "Pontos",
        "reb_mean": "Rebotes",
        "ast_mean": "Assistências",
        "true_shooting_pct_mean": "TS%",
        "effective_fg_pct_mean": "eFG%",
        "usage_pct_mean": "USG%",
        "naps": "NAPS",
        "style": "Estilo",
    }
    table = ranking[list(display_columns)].rename(columns=display_columns)
    st.dataframe(
        table.style.format(
            {
                "Minutos": "{:.1f}",
                "Pontos": "{:.1f}",
                "Rebotes": "{:.1f}",
                "Assistências": "{:.1f}",
                "TS%": "{:.1%}",
                "eFG%": "{:.1%}",
                "USG%": "{:.1f}%",
                "NAPS": "{:.0f}",
            },
            na_rep="—",
        ),
        hide_index=True,
        use_container_width=True,
    )

with tab_profile:
    selection = components.persistent_selectbox(
        "Selecione um jogador",
        player_options,
        query_key="player",
        key=f"profile_player_select_{source}",
    )
    selected_id = player_id_by_label[selection]

    full_player_history = (
        player_games[player_games["player_id"] == selected_id].sort_values("game_date")
    )

    st.markdown("#### Filtros do histórico")
    history_min_date = full_player_history["game_date"].min().date()
    history_max_date = full_player_history["game_date"].max().date()
    filter_cols = st.columns(5)
    with filter_cols[0]:
        start_date = st.date_input(
            "De",
            value=history_min_date,
            min_value=history_min_date,
            max_value=history_max_date,
            key=f"profile_start_date_{source}_{selected_id}",
        )
    with filter_cols[1]:
        end_date = st.date_input(
            "Até",
            value=history_max_date,
            min_value=history_min_date,
            max_value=history_max_date,
            key=f"profile_end_date_{source}_{selected_id}",
        )
    with filter_cols[2]:
        home_away_filter = st.selectbox(
            "Casa/Fora", ["Todos", "Casa", "Fora"], key=f"profile_home_away_{source}_{selected_id}"
        )
    with filter_cols[3]:
        opponent_options = ["Todos"] + sorted(full_player_history["opponent"].dropna().unique())
        opponent_filter = st.selectbox(
            "Adversário", opponent_options, key=f"profile_opponent_{source}_{selected_id}"
        )
    with filter_cols[4]:
        min_minutes = st.number_input(
            "Minutos mínimos", 0, 48, 0, key=f"profile_min_minutes_{source}_{selected_id}"
        )
    st.caption(
        "Os filtros afetam só esta visualização (métricas, consistência e gráficos "
        "abaixo) — os modelos de projeção continuam usando o histórico completo do "
        "jogador para calcular as médias móveis."
    )
    components.clear_filters_button(
        [
            f"profile_start_date_{source}_{selected_id}",
            f"profile_end_date_{source}_{selected_id}",
            f"profile_home_away_{source}_{selected_id}",
            f"profile_opponent_{source}_{selected_id}",
            f"profile_min_minutes_{source}_{selected_id}",
        ]
    )

    filtered = full_player_history[
        (full_player_history["game_date"] >= pd.Timestamp(start_date))
        & (full_player_history["game_date"] <= pd.Timestamp(end_date))
        & (full_player_history["minutes"] >= min_minutes)
    ]
    if home_away_filter == "Casa":
        filtered = filtered[filtered["is_home"]]
    elif home_away_filter == "Fora":
        filtered = filtered[~filtered["is_home"]]
    if opponent_filter != "Todos":
        filtered = filtered[filtered["opponent"] == opponent_filter]

    if filtered.empty:
        st.warning("Nenhum jogo encontrado com esses filtros.")
    else:
        components.sample_size_caption(len(filtered), len(full_player_history), unit="jogos")
        metrics = st.columns(5)
        metrics[0].metric("Jogos", len(filtered))
        metrics[1].metric("Minutos", f"{filtered['minutes'].mean():.1f}")
        metrics[2].metric("Pontos", f"{filtered['pts'].mean():.1f}")
        metrics[3].metric("Rebotes", f"{filtered['reb'].mean():.1f}")
        metrics[4].metric("Assistências", f"{filtered['ast'].mean():.1f}")

        efficiency = st.columns(4)
        efficiency[0].metric("TS%", f"{filtered['true_shooting_pct'].mean():.1%}")
        efficiency[1].metric("eFG%", f"{filtered['effective_fg_pct'].mean():.1%}")
        efficiency[2].metric("USG%", f"{filtered['usage_pct'].mean():.1f}%")
        efficiency[3].metric("AST/TO", f"{filtered['ast_to_ratio'].mean():.2f}")

        st.markdown("#### Consistência (pontos por jogo)")
        pts_mean = filtered["pts"].mean()
        pts_std = filtered["pts"].std()
        consistency = pd.DataFrame(
            {
                "Indicador": ["Média", "Mediana", "Desvio-padrão", "Coef. de variação", "P25", "P75"],
                "Valor": [
                    pts_mean,
                    filtered["pts"].median(),
                    pts_std,
                    pts_std / pts_mean if pts_mean else float("nan"),
                    filtered["pts"].quantile(0.25),
                    filtered["pts"].quantile(0.75),
                ],
            }
        )
        st.dataframe(
            consistency.style.format({"Valor": "{:.2f}"}),
            hide_index=True,
            use_container_width=True,
        )

        # Data da(s) troca(s) de time na carreira inteira (não só no recorte
        # filtrado), para marcar nos gráficos abaixo — a primeira "passagem"
        # não conta como troca, é só o começo do histórico do jogador.
        stints = assign_team_stints(full_player_history)
        trade_dates = stints.loc[stints["games_since_trade"] == 0, "game_date"].iloc[1:]

        st.markdown("#### Evolução recente (pontos por jogo)")
        figure = px.line(
            filtered,
            x="game_date",
            y="pts",
            markers=True,
            color_discrete_sequence=["#F97316"],
        )
        for trade_date in trade_dates:
            figure.add_vline(x=trade_date.timestamp() * 1000, line_dash="dash", line_color="#93a1ac")
        figure.update_layout(
            height=320,
            xaxis_title=None,
            yaxis_title="Pontos",
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(figure, use_container_width=True)

        st.markdown("#### Evolução recente (minutos por jogo)")
        minutes_figure = px.line(
            filtered,
            x="game_date",
            y="minutes",
            markers=True,
            color_discrete_sequence=["#4c9be8"],
        )
        for trade_date in trade_dates:
            minutes_figure.add_vline(
                x=trade_date.timestamp() * 1000, line_dash="dash", line_color="#93a1ac"
            )
        minutes_figure.update_layout(
            height=320,
            xaxis_title=None,
            yaxis_title="Minutos",
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(minutes_figure, use_container_width=True)
        if len(trade_dates) > 0:
            st.caption("Linhas tracejadas marcam datas de troca de time.")

    st.markdown("#### NAPS e estilo de jogo")
    index_row = player_index[player_index["player_id"] == selected_id]
    if index_row.empty:
        st.info(
            "Este jogador ainda não tem jogos/minutos suficientes para entrar no "
            "grupo de comparação do NAPS."
        )
    else:
        index_row = index_row.iloc[0]
        naps_col, style_col = st.columns(2)
        naps_col.metric("NAPS", f"{index_row['naps']:.0f}")
        style_col.metric("Estilo", index_row["style"])

        dimensions = list(DIMENSION_LABELS)
        radar = go.Figure()
        radar.add_trace(
            go.Scatterpolar(
                r=[index_row[dimension] for dimension in dimensions],
                theta=[DIMENSION_LABELS[dimension] for dimension in dimensions],
                fill="toself",
                line_color="#F97316",
            )
        )
        radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False,
            height=380,
            margin=dict(l=40, r=40, t=20, b=20),
        )
        st.plotly_chart(radar, use_container_width=True)
        st.caption(
            "Percentil (0-100) entre os jogadores qualificados (mínimo de jogos e "
            "minutos). NAPS é uma média ponderada dessas dimensões."
        )

with tab_compare:
    selected_labels = st.multiselect(
        "Selecione de 2 a 4 jogadores",
        player_options,
        max_selections=4,
        key=f"compare_players_select_{source}",
    )

    if len(selected_labels) < 2:
        st.info("Selecione pelo menos 2 jogadores para comparar.")
    else:
        selected_ids = [player_id_by_label[label] for label in selected_labels]
        comparison = compare_players(player_games, selected_ids)
        st.dataframe(comparison, use_container_width=True)

with tab_projection:
    st.caption(
        "A média da temporada mais recente disponível é a referência inicial para "
        "pontos, rebotes e assistências. A projeção ajusta essa base conforme minutos, "
        "forma recente, contexto do adversário e jogos já disputados na passagem pelo "
        "time atual. A referência perde peso gradualmente quando há evidências de uma "
        "nova função. Não usa informação confirmada de lesões ou disponibilidade dos companheiros."
    )

    try:
        bundle = _train_projection_bundle(player_games, team_games)
    except ValueError as error:
        st.warning(str(error))
        st.stop()

    projection_selection = st.selectbox(
        "Selecione um jogador",
        player_options,
        index=0,
        key=f"projection_player_select_{source}",
    )
    projection_id = player_id_by_label[projection_selection]

    known_seasons = (
        player_games["season"].dropna().astype(str).unique().tolist()
        if "season" in player_games.columns
        else []
    )
    known_years = [season_start_year(value) for value in known_seasons]
    known_years = [int(year) for year in known_years if pd.notna(year)]
    now = pd.Timestamp.now()
    current_season_start = now.year if now.month >= 7 else now.year - 1
    default_target_start = max([current_season_start, *known_years])
    default_target_season = f"{default_target_start}-{str(default_target_start + 1)[-2:]}"
    next_target_start = default_target_start + 1
    target_season_options = [
        default_target_season,
        f"{next_target_start}-{str(next_target_start + 1)[-2:]}",
    ]
    target_season = st.selectbox(
        "Temporada-alvo da previsão",
        target_season_options,
        index=0,
        help=(
            "A referência estatística será a temporada imediatamente anterior à escolhida. "
            "Se essa temporada não existir na base, o sistema usa a temporada histórica mais recente."
        ),
    )

    # Identifica automaticamente o próximo jogo pelo calendário oficial da NBA.
    # A última equipe vista no histórico serve apenas como sugestão: após uma
    # troca na offseason, o usuário pode selecionar manualmente a equipe atual.
    projection_history = player_games[
        player_games["player_id"] == projection_id
    ].sort_values("game_date")
    historical_team = (
        str(projection_history.iloc[-1]["team"]).strip().upper()
        if not projection_history.empty
        else ""
    )
    schedule_team_code: str | None = None
    next_game: dict | None = None
    scheduled_opponent_name: str | None = None
    schedule_error: str | None = None

    if source == "real":
        team_codes = sorted(TEAM_ABBREVIATION_TO_NAME)
        team_default_index = (
            team_codes.index(historical_team) if historical_team in team_codes else 0
        )
        schedule_team_code = st.selectbox(
            "Equipe atual para localizar o próximo jogo",
            team_codes,
            index=team_default_index,
            format_func=lambda code: f"{code} — {TEAM_ABBREVIATION_TO_NAME[code]}",
            key=f"next_game_team_{source}_{projection_id}",
            help=(
                "A equipe histórica é selecionada por padrão. Se o jogador mudou de time "
                "nesta offseason e ainda não há jogos dele pela nova equipe na base, "
                "escolha aqui a equipe atual para procurar o confronto correto."
            ),
        )
        retry_state_key = f"nba_schedule_retry_token_{source}"
        if st.button("Atualizar calendário oficial", key=f"refresh_nba_schedule_{source}_{projection_id}"):
            st.session_state[retry_state_key] = int(st.session_state.get(retry_state_key, 0)) + 1
        retry_token = int(st.session_state.get(retry_state_key, 0))
        with st.spinner("Consultando o calendário oficial da NBA…"):
            official_schedule, schedule_error = _load_nba_schedule(retry_token)
        if schedule_error is None:
            next_game = get_next_game_for_team(official_schedule, schedule_team_code)

        if next_game is not None:
            scheduled_opponent_name = str(next_game["opponent_name"])
            schedule_day = next_game["game_date"]
            home_away_text = "em casa" if next_game["is_home_for_team"] else "fora de casa"
            kickoff = pd.to_datetime(
                next_game.get("game_datetime_utc"), errors="coerce", utc=True
            )
            kickoff_text = (
                f" às {kickoff.tz_convert('America/New_York').strftime('%H:%M')} ET"
                if pd.notna(kickoff)
                else ""
            )
            st.success(
                f"Próximo confronto encontrado: **{TEAM_ABBREVIATION_TO_NAME[schedule_team_code]} "
                f"x {scheduled_opponent_name}**, {schedule_day.strftime('%d/%m/%Y')} "
                f"({home_away_text}){kickoff_text}. A previsão será calculada para esse jogo."
            )
        elif schedule_error:
            st.warning(
                "Não foi possível consultar o calendário oficial agora. "
                "Você ainda pode preencher o confronto manualmente. " + schedule_error
            )
        else:
            st.info(
                "Não encontrei um jogo futuro agendado para essa equipe no calendário. "
                "Confira a equipe selecionada ou informe o cenário manualmente."
            )
    else:
        st.info(
            "A base demonstrativa contém jogadores sintéticos; por isso, não é possível "
            "associá-los automaticamente à agenda real da NBA. Use os campos manuais abaixo."
        )

    schedule_target_date = next_game["game_date"] if next_game else date.today() + timedelta(days=1)
    is_home_default = bool(next_game["is_home_for_team"]) if next_game else True
    last_history_date = (
        pd.Timestamp(projection_history.iloc[-1]["game_date"]).date()
        if not projection_history.empty
        else date.today()
    )
    calendar_gap = max(0, (schedule_target_date - last_history_date).days - 1)
    rest_days_default = min(7, calendar_gap)
    if calendar_gap > 14:
        st.warning(
            "O histórico mais recente deste jogador está distante do próximo jogo. "
            "A projeção usa o que há na base e pode não refletir uma rotação ou função nova."
        )

    col_home, col_rest, col_opponent, col_target_date = st.columns(4)
    with col_home:
        is_home = st.radio(
            "Mando de quadra",
            ["Casa", "Fora"],
            index=0 if is_home_default else 1,
            horizontal=True,
            key=f"projection_home_{source}_{projection_id}_{schedule_team_code or 'manual'}",
        ) == "Casa"
    with col_rest:
        rest_days = st.number_input(
            "Dias de descanso",
            0,
            7,
            rest_days_default,
            key=f"projection_rest_{source}_{projection_id}_{schedule_team_code or 'manual'}",
            help="Estimado pela diferença entre a data do último jogo disponível e a data-alvo.",
        )
    with col_opponent:
        opponent_def_rating: float | None = None
        available_opponent_names = available_teams(team_games) if team_games is not None and not team_games.empty else []
        opponent_options = list(available_opponent_names)
        if scheduled_opponent_name and scheduled_opponent_name not in opponent_options:
            opponent_options.append(scheduled_opponent_name)
        opponent_options = sorted(set(opponent_options))
        if opponent_options:
            opponent_choices = list(opponent_options)
            if source == "real" and next_game is None:
                opponent_choices = ["Selecione manualmente"] + opponent_choices
            default_opponent_index = (
                opponent_choices.index(scheduled_opponent_name)
                if scheduled_opponent_name in opponent_choices
                else 0
            )
            selected_opponent_value = st.selectbox(
                "Próximo adversário",
                opponent_choices,
                index=default_opponent_index,
                key=f"projection_opponent_{source}_{projection_id}_{schedule_team_code or 'manual'}",
            )
            selected_opponent = (
                None if selected_opponent_value == "Selecione manualmente" else selected_opponent_value
            )
            if (
                selected_opponent is not None
                and team_games is not None
                and selected_opponent in available_opponent_names
            ):
                try:
                    opponent_def_rating = team_snapshot(team_games, selected_opponent)["def_rating"]
                except ValueError:
                    opponent_def_rating = None
            if selected_opponent is not None and opponent_def_rating is None:
                st.caption(
                    "Rating defensivo específico não encontrado na base; a previsão usará "
                    "a referência média da liga para este fator."
                )
        else:
            selected_opponent = st.text_input(
                "Próximo adversário",
                value=scheduled_opponent_name or "",
                key=f"projection_opponent_text_{source}_{projection_id}_{schedule_team_code or 'manual'}",
                placeholder="Ex.: Boston Celtics",
            ).strip() or None
    with col_target_date:
        target_game_date = st.date_input(
            "Data do jogo previsto",
            value=schedule_target_date,
            help=(
                "Quando o calendário oficial está disponível, este campo começa na data do próximo jogo. "
                "Você pode alterá-la manualmente para simular outro confronto."
            ),
            key=f"target_game_date_{source}_{projection_id}_{schedule_team_code or 'manual'}",
        )

    if next_game and target_game_date != next_game["game_date"]:
        st.warning(
            "A data escolhida é diferente da data do próximo jogo encontrado. "
            "A projeção será registrada para a data escolhida; confirme o adversário e o mando."
        )

    snapshot = player_snapshot(player_games, projection_id, target_season=target_season)
    prediction = predict_player_game(
        bundle,
        snapshot,
        is_home=is_home,
        rest_days=rest_days,
        opponent_def_rating=opponent_def_rating,
    )

    projection_games_played = int((player_games["player_id"] == projection_id).sum())
    states.small_sample_warning(projection_games_played, threshold=15)

    st.markdown("#### Projeção do próximo jogo")
    projection_metrics = st.columns(4)
    projection_metrics[0].metric("Minutos", f"{prediction.minutes:.1f}")
    projection_metrics[1].metric("Pontos", f"{prediction.stats['pts']:.1f}")
    projection_metrics[2].metric("Rebotes", f"{prediction.stats['reb']:.1f}")
    projection_metrics[3].metric("Assistências", f"{prediction.stats['ast']:.1f}")

    baseline_label = snapshot.get("prev_season_label", "histórico disponível")
    st.markdown(f"#### Comparação com a temporada-base ({baseline_label})")
    baseline_columns = st.columns(3)
    baseline_descriptions = (
        ("pts", "Pontos", "prev_season_pts_avg"),
        ("reb", "Rebotes", "prev_season_reb_avg"),
        ("ast", "Assistências", "prev_season_ast_avg"),
    )
    for column, (stat, label, baseline_key) in zip(
        baseline_columns, baseline_descriptions, strict=True
    ):
        baseline_value = float(snapshot.get(baseline_key, 0.0))
        projected_value = float(prediction.stats[stat])
        column.metric(
            f"Média-base — {label}",
            f"{baseline_value:.1f}",
            delta=f"{projected_value - baseline_value:+.1f} na projeção",
            delta_color="normal",
        )
    st.caption(
        "O baseline é a média por jogo da temporada mais recente disponível nos dados. "
        "A estimativa usa também a taxa por minuto dessa temporada para ajustar os "
        "resultados aos minutos previstos. Após uma troca de time, a referência anual "
        "tem maior peso no início e diminui conforme chegam partidas do novo stint."
    )

    if st.button("Registrar esta previsão"):
        projection_player_name = players.loc[
            players["player_id"] == projection_id, "player_name"
        ].iloc[0]
        log_player_prediction(
            projection_id,
            projection_player_name,
            selected_opponent,
            is_home,
            prediction.minutes,
            prediction.stats["pts"],
            prediction.stats["reb"],
            prediction.stats["ast"],
            prediction.confidence,
            target_game_date=target_game_date.isoformat(),
        )
        st.success(
            f"Previsão registrada para {target_game_date.strftime('%d/%m/%Y')}. "
            "Acompanhe em 'Desempenho': ela só será resolvida quando houver dados "
            "do jogador para a data-alvo e o contexto de adversário/mando coincidir."
        )

    st.markdown("###### Como a projeção de pontos foi montada")
    chain_columns = st.columns(4)
    chain_columns[0].metric("Pontos — modelo direto", f"{prediction.stats['pts']:.1f}")
    chain_columns[1].metric("Referência FGA × TS%", f"{prediction.chain_pts:.1f}")
    chain_columns[2].metric("Arremessos previstos (FGA)", f"{prediction.projected_fga:.1f}")
    chain_columns[3].metric("Aproveitamento previsto (TS%)", f"{prediction.projected_ts_pct:.1%}")
    st.caption(
        "A projeção principal usa um regressor direto de pontos por minuto × minutos esperados, "
        "com histórico recente, volume ofensivo, eficiência, rotação e contexto. A conta FGA × TS% "
        "é exibida como referência interpretável independente; lances livres nessa referência usam "
        "a proporção histórica do próprio jogador (FTA/FGA)."
    )

    interval_data = pd.DataFrame(
        {
            "Estatística": ["Pontos", "Rebotes", "Assistências"],
            "Mínimo": [
                prediction.stats_low["pts"],
                prediction.stats_low["reb"],
                prediction.stats_low["ast"],
            ],
            "Central": [
                prediction.stats["pts"],
                prediction.stats["reb"],
                prediction.stats["ast"],
            ],
            "Máximo": [
                prediction.stats_high["pts"],
                prediction.stats_high["reb"],
                prediction.stats_high["ast"],
            ],
        }
    )
    st.dataframe(
        interval_data.style.format(
            {"Mínimo": "{:.1f}", "Central": "{:.1f}", "Máximo": "{:.1f}"}
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        f"Confiança do modelo: {prediction.confidence}. "
        "É uma classe de incerteza relativa baseada no erro histórico, quantidade de histórico "
        "e estabilidade do stint — não uma probabilidade de acerto. O intervalo é experimental "
        "e sua cobertura deve ser acompanhada na auditoria das previsões resolvidas."
    )

    st.markdown("#### Probabilidade de over/under")
    stat_labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}
    col_stat, col_line = st.columns(2)
    with col_stat:
        over_under_stat = st.selectbox(
            "Estatística", list(stat_labels.keys()), format_func=lambda key: stat_labels[key]
        )
    with col_line:
        default_line = round(prediction.stats[over_under_stat] * 2) / 2
        line = st.number_input("Line", value=default_line, step=0.5)

    over_pct = over_probability(
        prediction.stats[over_under_stat], bundle.residual_std[over_under_stat], line
    )
    over_under_columns = st.columns(2)
    over_under_columns[0].metric(f"Over {line:g}", f"{over_pct:.0%}")
    over_under_columns[1].metric(f"Under {line:g}", f"{1 - over_pct:.0%}")
    st.caption(
        "Probabilidade estatística calculada a partir da previsão do modelo e do seu erro "
        "histórico (assumindo distribuição normal em torno da previsão) — não é uma odds de "
        "mercado nem orientação de aposta; o projeto não usa odds."
    )

    st.markdown("#### Distribuição de resultados")
    buckets = range_probabilities(
        prediction.stats[over_under_stat], bundle.residual_std[over_under_stat]
    )
    distribution_figure = go.Figure(
        go.Bar(
            x=[bucket["label"] for bucket in buckets],
            y=[bucket["probability"] for bucket in buckets],
            text=[f"{bucket['probability']:.0%}" for bucket in buckets],
            textposition="outside",
            marker_color="#d9560f",
        )
    )
    distribution_figure.update_layout(
        yaxis_tickformat=".0%",
        yaxis_title="Probabilidade",
        xaxis_title=stat_labels[over_under_stat],
        height=320,
        margin=dict(t=10, b=10),
    )
    st.plotly_chart(distribution_figure, use_container_width=True)
    st.caption(
        "Faixas geradas a partir da própria previsão: largura = erro histórico do modelo "
        "arredondado (mínimo 1), 5 faixas centradas na projeção. Mesma aproximação normal do "
        "over/under acima, fatiada em vários pontos de corte."
    )

    st.markdown("#### Qualidade do modelo (erro médio absoluto)")
    quality_metrics = st.columns(4)
    quality_metrics[0].metric("Minutos", f"{bundle.metrics['minutes_mae']:.1f}")
    quality_metrics[1].metric("Pontos", f"{bundle.metrics['pts_mae']:.1f}")
    quality_metrics[2].metric("Rebotes", f"{bundle.metrics['reb_mae']:.1f}")
    quality_metrics[3].metric("Assistências", f"{bundle.metrics['ast_mae']:.1f}")
