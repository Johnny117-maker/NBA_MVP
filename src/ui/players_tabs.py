"""Abas Visão geral, Perfil individual e Comparação da página Jogadores."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.player_features import (
    assign_team_stints,
)
from src.player_index import DIMENSION_LABELS
from src.player_metrics import compare_players
from src.ui import components
from src.ui.insights import performance_bars, player_card


def overview_tab(player_index, players, source, summary) -> None:
    """Aba Visão geral."""
    components.section_header(
        "Panorama de jogadores", "Busque um atleta ou filtre a equipe para explorar o ranking."
    )
    player_search = st.text_input(
        "Buscar jogador", placeholder="Digite o nome do atleta…", key="ranking_search"
    )
    st.caption(
        "NAPS (0–100) é um índice experimental relativo aos jogadores qualificados desta base."
    )
    teams = ["Todos"] + sorted(players["team"].unique())
    team_filter = st.selectbox("Filtrar por time", teams, index=0, key=f"team_filter_{source}")

    ranking = summary.merge(player_index[["player_id", "naps", "style"]], on="player_id", how="left")
    ranking = ranking if team_filter == "Todos" else ranking[ranking["team"] == team_filter]
    if player_search.strip():
        ranking = ranking[ranking["player_name"].str.contains(player_search.strip(), case=False, regex=False)]
    ranking = ranking.sort_values("naps", ascending=False, na_position="last")
    st.caption(f"{len(ranking)} jogadores encontrados.")

    for column, (_, athlete) in zip(st.columns(3), ranking.head(3).iterrows(), strict=False):
        with column:
            player_card(
                str(athlete["player_name"]), str(athlete["team"]), float(athlete["pts_mean"]),
                float(athlete["reb_mean"]), float(athlete["ast_mean"]),
                detail=f"NAPS {athlete['naps']:.0f}" if pd.notna(athlete["naps"]) else "Sem NAPS",
            )

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


def profile_tab(player_games, player_id_by_label, player_index, player_options, source) -> None:
    """Aba Perfil individual."""
    selection = components.persistent_selectbox(
        "Selecione um jogador",
        player_options,
        query_key="player",
        key=f"profile_player_select_{source}",
    )
    selected_id = player_id_by_label[selection]
    if source == "real" and st.button("Ver marcações e encaixes defensivos", key="open_player_matchups"):
        st.session_state["matchups_player_id"] = int(selected_id)
        st.switch_page("pages/13_Marcacoes.py")

    full_player_history = player_games[player_games["player_id"] == selected_id].sort_values("game_date")

    latest_player = full_player_history.iloc[-1]
    profile_recent = full_player_history.tail(10)
    player_card(
        str(latest_player["player_name"]), str(latest_player["team"]),
        float(profile_recent["pts"].mean()), float(profile_recent["reb"].mean()),
        float(profile_recent["ast"].mean()), detail=f"Últimos {len(profile_recent)} jogos coletados",
    )

    with st.expander("Filtros do histórico", expanded=False):
        st.markdown("#### Filtros do histórico")
        history_min_date = full_player_history["game_date"].min().date()
        history_max_date = full_player_history["game_date"].max().date()
        filter_cols = [*st.columns(2), *st.columns(3)]
        with filter_cols[0]:
            start_date = st.date_input(
                "De",
                value=history_min_date,
                format="DD/MM/YYYY",
                min_value=history_min_date,
                max_value=history_max_date,
                key=f"profile_start_date_{source}_{selected_id}",
            )
        with filter_cols[1]:
            end_date = st.date_input(
                "Até",
                value=history_max_date,
                format="DD/MM/YYYY",
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
        with st.container(border=True):
            components.section_header("Desempenho por partida", "Últimos 20 jogos do recorte selecionado.")
            stat_col, line_col = st.columns([2, 1])
            stat_labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências", "fg3m": "Cestas de 3"}
            with stat_col:
                profile_stat = st.radio(
                    "Indicador do gráfico", list(stat_labels), format_func=stat_labels.get,
                    horizontal=True, key=f"profile_bar_stat_{source}_{selected_id}",
                )
            with line_col:
                profile_line = st.number_input(
                    "Linha de referência", min_value=0.0,
                    value=round(float(filtered[profile_stat].mean()) * 2) / 2, step=0.5,
                    key=f"profile_bar_line_{source}_{selected_id}_{profile_stat}",
                )
            st.plotly_chart(
                performance_bars(filtered, profile_stat, stat_labels[profile_stat], profile_line),
                use_container_width=True,
            )
            above = int(filtered.tail(20)[profile_stat].gt(profile_line).sum())
            st.caption(
                f"{above} de {min(20, len(filtered))} partidas acima da referência. "
                "Verde: acima; vermelho: até a linha, incluindo igualdade. Frequência histórica."
            )
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
            minutes_figure.add_vline(x=trade_date.timestamp() * 1000, line_dash="dash", line_color="#93a1ac")
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
            "Este jogador ainda não tem jogos/minutos suficientes para entrar no grupo de comparação do NAPS."
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


def compare_tab(player_games, player_id_by_label, player_options, source) -> None:
    """Aba Comparação."""
    components.section_header(
        "Lado a lado", "Selecione até quatro atletas para comparar os mesmos indicadores."
    )
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
