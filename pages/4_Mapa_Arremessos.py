from __future__ import annotations

import pandas as pd
import streamlit as st

from src.court_chart import (
    shot_heatmap_chart,
    shot_hexbin_chart,
    shot_points_chart,
    zone_frequency_trend_chart,
)
from src.shot_features import (
    compare_periods,
    compare_to_league,
    compare_to_opponent_defense,
    filter_shots,
    league_zone_rates,
    opponent_zone_defense,
    shot_indicators,
    zone_summary,
)
from src.shot_model import (
    add_zone_model_features,
    expected_fg_points,
    fill_missing_features_with_league_average,
    live_zone_snapshot,
    predict_zone_distribution,
    train_zone_models,
)
from src.shot_storage import (
    count_player_shots,
    list_players_with_shots,
    read_player_shots,
    read_shots_for_zone_reference,
)
from src.store import DEFAULT_DB_PATH
from src.ui import components, states, theme
from src.ui.explanations import explain_zone_shift
from src.ui.formatters import format_int_br

MIN_GAMES_FOR_ZONE_MODELS = 30

st.set_page_config(
    page_title="Mapa de Arremessos — NBA Analytics Lab",
    page_icon="🎯",
    layout="wide",
)

theme.inject_base_style()

def _render_period_comparison(comparison: pd.DataFrame, label_a: str, label_b: str) -> None:
    st.markdown(f"> {explain_zone_shift(comparison, label_a=label_a, label_b=label_b)}")
    display = comparison[
        ["zone_label", "attempts_a", "attempts_b", "fg_pct_a", "fg_pct_b", "points_per_shot_a", "points_per_shot_b"]
    ].rename(
        columns={
            "zone_label": "Zona",
            "attempts_a": f"Tentativas ({label_a})",
            "attempts_b": f"Tentativas ({label_b})",
            "fg_pct_a": f"FG% ({label_a})",
            "fg_pct_b": f"FG% ({label_b})",
            "points_per_shot_a": f"Pts/tent. ({label_a})",
            "points_per_shot_b": f"Pts/tent. ({label_b})",
        }
    )
    st.dataframe(
        display.style.format(
            {
                f"FG% ({label_a})": "{:.1%}",
                f"FG% ({label_b})": "{:.1%}",
                f"Pts/tent. ({label_a})": "{:.2f}",
                f"Pts/tent. ({label_b})": "{:.2f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


st.markdown("## 🎯 Mapa de Arremessos")
st.caption(
    "De onde cada jogador arremessa, com que eficiência e como isso mudou ao longo "
    "do tempo. Estimativas educacionais, não orientação de apostas."
)

with st.sidebar:
    st.header("Configuração")
    st.caption(
        "Este projeto produz estimativas esportivas educacionais. "
        "Não utiliza odds e não fornece orientação de apostas."
    )

shots_collected = count_player_shots(DEFAULT_DB_PATH)
if shots_collected == 0:
    states.empty_state(
        "Nenhum arremesso coletado ainda",
        "A coleta é incremental e pode levar um tempo — cada execução coleta um "
        "lote e pode ser repetida para continuar de onde parou.",
        actions=[
            (
                "Coletar arremessos",
                "rode 'python scripts/update_shots.py' (depois de já ter rodado "
                "'python scripts/update_data.py') e recarregue esta página",
            )
        ],
    )


# `st.cache_resource` (não `cache_data`): a base já passa de 1 milhão de
# arremessos, e `cache_data` faz pickle do resultado a cada leitura do cache —
# nessa escala, isso sozinho já esgotou memória. `cache_resource` guarda o
# objeto em memória sem serializar; seguro aqui porque nada no resto da
# página modifica esses DataFrames no lugar (só lê, filtra e agrega em cópias
# novas).
@st.cache_resource(show_spinner=False)
def _load_players() -> pd.DataFrame:
    return list_players_with_shots(DEFAULT_DB_PATH)


@st.cache_resource(show_spinner=False)
def _load_zone_reference() -> pd.DataFrame:
    return read_shots_for_zone_reference(DEFAULT_DB_PATH)


@st.cache_data(show_spinner=False)
def _load_player_shots(player_id: int) -> pd.DataFrame:
    return read_player_shots(DEFAULT_DB_PATH, player_id=player_id)


players = _load_players()
zone_reference = _load_zone_reference()

player_options = players["player_name"].tolist()
player_id_by_name = dict(zip(players["player_name"], players["player_id"]))

selector_col, season_col = st.columns([2, 1])
with selector_col:
    selected_name = components.persistent_selectbox(
        "Jogador", player_options, query_key="player"
    )
selected_id = player_id_by_name[selected_name]

player_shots_all_seasons = _load_player_shots(selected_id)
seasons = sorted(player_shots_all_seasons["season"].unique(), reverse=True)
with season_col:
    selected_season = components.persistent_selectbox(
        "Temporada", seasons, query_key="season"
    )

shots = filter_shots(player_shots_all_seasons, season=selected_season)

components.source_badge("NBA API — dados reais", components.db_last_updated(DEFAULT_DB_PATH))
st.caption(
    f"{format_int_br(len(shots))} arremessos coletados para "
    f"{selected_name} na temporada {selected_season}. Referência de liga: "
    f"{format_int_br(len(zone_reference))} arremessos de todos os jogadores já "
    "coletados nesta base (ainda não é a liga inteira — cresce a cada coleta)."
)

league_rates = league_zone_rates(zone_reference)
league_points_per_shot = shot_indicators(zone_reference).get("points_per_shot")

if shots.empty:
    st.warning("Nenhum arremesso encontrado para esse jogador nessa temporada.")
    st.stop()

indicators = shot_indicators(shots, league_rates=league_rates)

components.metric_row(
    [
        {"label": "Tentativas", "value": format_int_br(indicators["total_attempts"])},
        {"label": "FG%", "value": f"{indicators['fg_pct']:.1%}"},
        {"label": "eFG%", "value": f"{indicators['efg_pct']:.1%}"},
        {"label": "Pontos/tentativa", "value": f"{indicators['points_per_shot']:.2f}"},
        {"label": "Distância média", "value": f"{indicators['avg_distance']:.1f} pés"},
        {"label": "Zona mais usada", "value": indicators["most_used_zone"]},
    ]
)

tab_points, tab_heatmap, tab_hexbin, tab_zones, tab_trend, tab_compare, tab_projections = st.tabs(
    ["Mapa de pontos", "Mapa de calor", "Mapa hexagonal", "Por zona", "Evolução", "Comparações", "Projeções"]
)

with tab_points:
    st.plotly_chart(shot_points_chart(shots), use_container_width=True)
    st.caption("Verde: convertido. Vermelho: errado.")

with tab_heatmap:
    st.plotly_chart(shot_heatmap_chart(shots), use_container_width=True)
    st.caption("Representa volume de tentativas, não eficiência.")

with tab_hexbin:
    st.plotly_chart(
        shot_hexbin_chart(shots, league_average_points_per_shot=league_points_per_shot),
        use_container_width=True,
    )
    st.caption(
        "Tamanho do hexágono: volume de tentativas. Cor: pontos por tentativa "
        "(vermelho acima da referência de liga, azul abaixo)."
    )

with tab_zones:
    summary = zone_summary(shots)
    compared = compare_to_league(summary, league_rates)
    display = compared[
        [
            "zone_label",
            "attempts",
            "makes",
            "frequency",
            "fg_pct",
            "shrunk_fg_pct",
            "points_per_shot",
            "diff_points_per_shot",
        ]
    ].rename(
        columns={
            "zone_label": "Zona",
            "attempts": "Tentativas",
            "makes": "Conversões",
            "frequency": "Frequência",
            "fg_pct": "FG%",
            "shrunk_fg_pct": "FG% (suavizado)",
            "points_per_shot": "Pontos/tentativa",
            "diff_points_per_shot": "Dif. vs. referência",
        }
    )
    st.dataframe(
        display.style.format(
            {
                "Frequência": "{:.1%}",
                "FG%": "{:.1%}",
                "FG% (suavizado)": "{:.1%}",
                "Pontos/tentativa": "{:.2f}",
                "Dif. vs. referência": "{:+.2f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "'FG% (suavizado)' puxa zonas com poucas tentativas em direção à referência "
        "de liga (suavização bayesiana) — protege contra amostra pequena, ex.: 3 de 4 "
        "não é tratado como 75% de verdade."
    )

    highlight_cols = st.columns(3)
    highlight_cols[0].metric("Zona mais eficiente", indicators["most_efficient_zone"] or "—")
    highlight_cols[1].metric(
        "Maior vantagem sobre a liga",
        indicators["best_diff_zone"] or "—",
        f"{indicators['best_diff_points_per_shot']:+.2f} pts/tentativa"
        if indicators["best_diff_zone"]
        else None,
    )
    highlight_cols[2].metric(
        "Muito volume, pouca eficiência", indicators["volume_low_efficiency_zone"] or "—"
    )

with tab_trend:
    st.plotly_chart(
        zone_frequency_trend_chart(player_shots_all_seasons), use_container_width=True
    )
    st.caption(
        "Frequência por categoria de zona ao longo de toda a carreira coletada "
        "(não só a temporada selecionada acima). Linhas tracejadas marcam troca de time."
    )

with tab_compare:
    comparison_mode = st.radio(
        "O que comparar?",
        ["Duas temporadas", "Primeiros × últimos N jogos", "Contra um adversário específico"],
        horizontal=True,
    )

    if comparison_mode == "Duas temporadas":
        if len(seasons) < 2:
            st.info("Esse jogador só tem uma temporada coletada nesta base — nada para comparar ainda.")
        else:
            season_col_a, season_col_b = st.columns(2)
            with season_col_a:
                season_a = st.selectbox(
                    "Temporada A", seasons, index=min(1, len(seasons) - 1), key="cmp_season_a"
                )
            with season_col_b:
                season_b = st.selectbox("Temporada B", seasons, index=0, key="cmp_season_b")

            shots_a = filter_shots(player_shots_all_seasons, season=season_a)
            shots_b = filter_shots(player_shots_all_seasons, season=season_b)
            _render_period_comparison(compare_periods(shots_a, shots_b), season_a, season_b)

    elif comparison_mode == "Primeiros × últimos N jogos":
        games_in_season = shots["game_id"].nunique()
        max_n = max(1, games_in_season // 2)
        n_games = st.slider(
            "Quantos jogos em cada ponta (dentro da temporada selecionada)?",
            1,
            max(1, min(20, max_n)),
            min(10, max(1, max_n)),
        )
        shots_first = filter_shots(shots, first_n_games=n_games)
        shots_last = filter_shots(shots, last_n_games=n_games)
        _render_period_comparison(
            compare_periods(shots_first, shots_last), f"Primeiros {n_games}", f"Últimos {n_games}"
        )
        st.caption("Compara a temporada selecionada acima com ela mesma, início × fim.")

    else:
        opponent_teams = sorted(zone_reference["opponent"].dropna().unique())
        chosen_opponent = st.selectbox("Adversário", opponent_teams)

        defense = opponent_zone_defense(zone_reference)
        compared = compare_to_opponent_defense(zone_summary(shots), defense, chosen_opponent)
        display = compared[
            [
                "zone_label",
                "attempts",
                "fg_pct",
                "points_per_shot",
                "attempts_against",
                "fg_pct_against",
                "points_per_shot_against",
                "diff_points_per_shot_vs_opponent",
            ]
        ].rename(
            columns={
                "zone_label": "Zona",
                "attempts": "Tentativas do jogador",
                "fg_pct": "FG% do jogador",
                "points_per_shot": "Pts/tent. do jogador",
                "attempts_against": f"Tentativas sofridas ({chosen_opponent})",
                "fg_pct_against": f"FG% permitido ({chosen_opponent})",
                "points_per_shot_against": f"Pts/tent. permitido ({chosen_opponent})",
                "diff_points_per_shot_vs_opponent": "Diferença",
            }
        )
        st.dataframe(
            display.style.format(
                {
                    "FG% do jogador": "{:.1%}",
                    "Pts/tent. do jogador": "{:.2f}",
                    f"FG% permitido ({chosen_opponent})": "{:.1%}",
                    f"Pts/tent. permitido ({chosen_opponent})": "{:.2f}",
                    "Diferença": "{:+.2f}",
                },
                na_rep="sem amostra",
            ),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"'Permitido ({chosen_opponent})' é calculado só com os arremessos de todos os "
            "jogadores já coletados nesta base contra esse time — não é a liga inteira, a "
            "amostra tende a melhorar conforme mais jogadores forem coletados. 'Diferença' "
            "positiva: o jogador costuma converter mais nessa zona do que esse adversário "
            "costuma permitir."
        )

with tab_projections:
    if len(zone_reference) < MIN_GAMES_FOR_ZONE_MODELS:
        st.info(
            f"São necessários pelo menos {MIN_GAMES_FOR_ZONE_MODELS} jogos coletados (de "
            "qualquer jogador, somados) para treinar os modelos de zona. Colete mais dados "
            "com 'python scripts/update_shots.py'."
        )
    else:

        @st.cache_data(show_spinner=False)
        def _zone_model_features(shots: pd.DataFrame) -> pd.DataFrame:
            return add_zone_model_features(shots)

        @st.cache_resource(show_spinner=False)
        def _train_zone_bundle(zone_games: pd.DataFrame):
            return train_zone_models(zone_games)

        with st.spinner("Treinando os modelos de zona..."):
            zone_games_with_features = _zone_model_features(zone_reference)
            zone_bundle = _train_zone_bundle(zone_games_with_features)

        st.caption(
            f"Modelos treinados com {format_int_br(len(zone_games_with_features))}"
            " jogos (de todos os jogadores já coletados) — um Ridge de participação e "
            "um de eficiência por zona (mesmo estilo dos modelos de minutos/pontos/"
            "rebotes/assistências da página 'Jogadores'). Minutos e FGA previstos "
            "continuam vindo de lá; aqui só entram a distribuição por zona e a "
            "eficiência por zona."
        )

        opponent_teams_proj = sorted(zone_reference["opponent"].dropna().unique())
        proj_col_a, proj_col_b = st.columns(2)
        with proj_col_a:
            projection_opponent = st.selectbox(
                "Próximo adversário", ["(nenhum)"] + opponent_teams_proj, key="proj_opponent"
            )
        recent_avg_fga = float(
            zone_games_with_features.loc[
                zone_games_with_features["player_id"] == selected_id, "total_fga"
            ]
            .tail(10)
            .mean()
        )
        default_fga = round(recent_avg_fga, 1) if pd.notna(recent_avg_fga) else 10.0
        with proj_col_b:
            projected_fga = st.number_input(
                "Arremessos de quadra previstos (FGA)",
                min_value=0.0,
                value=default_fga,
                step=0.5,
                help="Este módulo não prevê FGA — use a aba 'Projeções' da página "
                "'Jogadores' para isso, ou ajuste manualmente aqui.",
            )

        player_games_collected = int((zone_games_with_features["player_id"] == selected_id).sum())
        states.small_sample_warning(player_games_collected, threshold=15)

        defending_team = None if projection_opponent == "(nenhum)" else projection_opponent
        snapshot = live_zone_snapshot(
            zone_games_with_features, selected_id, defending_team, zone_reference
        )
        filled_snapshot = fill_missing_features_with_league_average(zone_bundle, snapshot)
        zone_prediction = predict_zone_distribution(zone_bundle, filled_snapshot)
        predicted_points = expected_fg_points(zone_prediction, pd.Series({0: projected_fga}))

        st.metric(
            "Pontos de bola-de-quadra esperados",
            f"{predicted_points.iloc[0]:.1f}",
            help="Só arremessos de quadra (2 e 3 pontos) — lance livre fica fora, o "
            "ShotChartDetail não coleta lance livre.",
        )

        display_prediction = zone_prediction[["zone_label", "predicted_share", "predicted_fg_pct"]].rename(
            columns={
                "zone_label": "Zona",
                "predicted_share": "Participação prevista",
                "predicted_fg_pct": "FG% previsto",
            }
        )
        st.dataframe(
            display_prediction.style.format({"Participação prevista": "{:.1%}", "FG% previsto": "{:.1%}"}),
            hide_index=True,
            use_container_width=True,
        )

        n_players_collected = zone_games_with_features["player_id"].nunique()
        st.caption(
            "Validação walk-forward (holdout cronológico, "
            "`src/shot_model.py::walk_forward_evaluate_zone_models`): o MAE de pontos de "
            "bola-de-quadra desta decomposição por zona fica bem abaixo do MAE de só "
            "prever a média constante (checado com os dados reais já coletados). Amostra "
            f"ainda pequena ({n_players_collected} jogadores coletados) — a defesa por "
            "zona de cada adversário, em especial, tende a melhorar conforme mais "
            "jogadores forem coletados."
        )
