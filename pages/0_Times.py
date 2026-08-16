from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.data import (
    available_teams,
    load_games,
    load_real_games,
    team_game_history,
    team_snapshot,
)
from src.model import predict_game, train_models
from src.simulation import simulate_score_distribution
from src.store import DEFAULT_DB_PATH, count_games, log_team_prediction
from src.ui import components, states, theme

st.set_page_config(
    page_title="Times — NBA Analytics Lab",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject_base_style()


@st.cache_data(show_spinner=False)
def demo_games() -> pd.DataFrame:
    return load_games()


@st.cache_resource(show_spinner=False)
def cached_train(games: pd.DataFrame):
    return train_models(games)


def probability_chart(home_team: str, away_team: str, home_probability: float):
    chart_data = pd.DataFrame(
        {
            "Time": [home_team, away_team],
            "Probabilidade": [home_probability, 1 - home_probability],
        }
    )
    figure = px.bar(
        chart_data,
        x="Probabilidade",
        y="Time",
        orientation="h",
        text=chart_data["Probabilidade"].map(lambda value: f"{value:.1%}"),
        color="Time",
        color_discrete_sequence=["#F97316", "#38BDF8"],
    )
    figure.update_traces(textposition="inside", textfont_size=16)
    figure.update_layout(
        showlegend=False,
        height=250,
        xaxis_tickformat=".0%",
        xaxis_range=[0, 1],
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title=None,
        yaxis_title=None,
    )
    return figure


def recent_form_chart(games: pd.DataFrame, home_team: str, away_team: str):
    frames = []
    for team in (home_team, away_team):
        history = team_game_history(games, team).tail(15).copy()
        history["Time"] = team
        history["Média móvel de vitórias"] = history["win"].rolling(5, min_periods=1).mean()
        frames.append(history)
    data = pd.concat(frames, ignore_index=True)
    figure = px.line(
        data,
        x="game_date",
        y="Média móvel de vitórias",
        color="Time",
        markers=True,
        color_discrete_sequence=["#F97316", "#38BDF8"],
    )
    figure.update_layout(
        height=330,
        yaxis_tickformat=".0%",
        yaxis_range=[0, 1],
        xaxis_title=None,
        yaxis_title="Forma (últimos 5)",
        legend_title=None,
        margin=dict(l=10, r=10, t=25, b=10),
    )
    return figure


def main() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>🏀 Times</h1>
            <p>Comparação de times, previsão experimental e explicação dos fatores do modelo.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    real_data_available = DEFAULT_DB_PATH.exists() and count_games(DEFAULT_DB_PATH) > 0

    with st.sidebar:
        st.header("Configuração")
        source_options = ["Base demonstrativa", "Dados reais (coletados)", "Enviar CSV"]
        source = st.radio(
            "Fonte dos dados",
            source_options,
            index=1 if real_data_available else 0,
            help=(
                "A base demonstrativa é sintética. Dados reais exigem rodar "
                "'python scripts/update_data.py' antes."
            ),
        )
        uploaded_file = None
        if source == "Enviar CSV":
            uploaded_file = st.file_uploader("Arquivo de partidas", type=["csv"])

        st.divider()
        st.caption(
            "Este projeto produz estimativas esportivas educacionais. "
            "Não utiliza odds e não fornece orientação de apostas."
        )

    try:
        if source == "Base demonstrativa":
            games = demo_games()
            is_demo = True
            last_updated = None
        elif source == "Dados reais (coletados)":
            if not DEFAULT_DB_PATH.exists():
                states.empty_state(
                    "Nenhum dado real encontrado ainda",
                    "Colete jogos reais antes de usar esta fonte.",
                    actions=[
                        ("Coletar dados", "vá até a página 'Dados e Atualizações' na barra lateral")
                    ],
                )
            games = load_real_games()
            is_demo = False
            last_updated = components.db_last_updated(DEFAULT_DB_PATH)
        elif uploaded_file is not None:
            games = load_games(uploaded_file)
            is_demo = False
            last_updated = None
        else:
            states.empty_state(
                "Nenhum arquivo enviado",
                "Envie um CSV de partidas ou selecione a base demonstrativa na barra lateral.",
            )

        with st.spinner("Treinando os modelos..."):
            bundle = cached_train(games)
    except (ValueError, TypeError, pd.errors.ParserError, FileNotFoundError) as error:
        states.error_state("Não foi possível treinar os modelos com esses dados.", detail=str(error))
        st.stop()

    components.source_badge(source, last_updated)
    if is_demo:
        components.note(
            "Os números desta tela são sintéticos e não representam a temporada atual da NBA."
        )

    teams = available_teams(games)
    selection_a, selection_b, rest_a, rest_b = st.columns([2, 2, 1, 1])
    with selection_a:
        home_team = st.selectbox("Time da casa", teams, index=0)
    with selection_b:
        away_options = [team for team in teams if team != home_team]
        away_team = st.selectbox("Time visitante", away_options, index=0)
    with rest_a:
        home_rest = st.number_input("Descanso casa", 1, 7, 2)
    with rest_b:
        away_rest = st.number_input("Descanso visitante", 1, 7, 2)

    home = team_snapshot(games, home_team)
    away = team_snapshot(games, away_team)
    prediction = predict_game(bundle, home, away, home_rest, away_rest)

    st.subheader("Cenário projetado")
    components.metric_row(
        [
            {"label": home_team, "value": f"{prediction.home_win_probability:.1%}", "delta": "mandante"},
            {"label": away_team, "value": f"{prediction.away_win_probability:.1%}", "delta": "visitante"},
            {
                "label": "Placar central",
                "value": f"{prediction.home_score:.0f} × {prediction.away_score:.0f}",
            },
            {"label": "Confiança", "value": prediction.confidence},
            {"label": "Jogos na base", "value": f"{len(games):,}".replace(",", ".")},
        ]
    )

    if st.button("Registrar esta previsão"):
        log_team_prediction(
            home_team,
            away_team,
            prediction.home_win_probability,
            prediction.home_score,
            prediction.away_score,
            prediction.confidence,
        )
        st.success(
            "Previsão registrada. Acompanhe em 'Desempenho' na barra lateral — "
            "lá dá para comparar com o resultado real depois que o jogo acontecer."
        )

    chart_column, score_column = st.columns([1.25, 1])
    with chart_column:
        st.plotly_chart(
            probability_chart(
                home_team, away_team, prediction.home_win_probability
            ),
            use_container_width=True,
        )
    with score_column:
        st.markdown("#### Intervalo provável de pontuação")
        interval_data = pd.DataFrame(
            {
                "Time": [home_team, away_team],
                "Mínimo": [prediction.home_score_low, prediction.away_score_low],
                "Central": [prediction.home_score, prediction.away_score],
                "Máximo": [prediction.home_score_high, prediction.away_score_high],
            }
        )
        st.dataframe(
            interval_data.style.format(
                {"Mínimo": "{:.0f}", "Central": "{:.0f}", "Máximo": "{:.0f}"}
            ),
            hide_index=True,
            use_container_width=True,
        )
        st.caption("Intervalo experimental de aproximadamente 80%, baseado no erro histórico.")

    tab_analysis, tab_factors, tab_simulation, tab_model = st.tabs(
        ["Comparativo", "Fatores", "Simulação", "Qualidade do modelo"]
    )

    with tab_analysis:
        comparison = pd.DataFrame(
            {
                "Indicador": [
                    "Eficiência ofensiva",
                    "Eficiência defensiva",
                    "Net Rating",
                    "Vitórias nos últimos 10",
                    "Pontos feitos",
                    "Pontos sofridos",
                ],
                home_team: [
                    home["off_rating"],
                    home["def_rating"],
                    home["net_rating"],
                    home["win_pct"],
                    home["points_for"],
                    home["points_against"],
                ],
                away_team: [
                    away["off_rating"],
                    away["def_rating"],
                    away["net_rating"],
                    away["win_pct"],
                    away["points_for"],
                    away["points_against"],
                ],
            }
        )
        left, right = st.columns([1, 1.4])
        with left:
            st.dataframe(
                comparison.style.format(
                    {home_team: "{:.2f}", away_team: "{:.2f}"}
                ),
                hide_index=True,
                use_container_width=True,
            )
        with right:
            st.plotly_chart(
                recent_form_chart(games, home_team, away_team),
                use_container_width=True,
            )

    with tab_factors:
        st.markdown(
            "Valores positivos favorecem o mandante; valores negativos favorecem o visitante."
        )
        factors = pd.DataFrame(prediction.factors, columns=["Fator", "Impacto"])
        factors["Direção"] = factors["Impacto"].map(
            lambda value: home_team if value >= 0 else away_team
        )
        factor_figure = px.bar(
            factors.sort_values("Impacto"),
            x="Impacto",
            y="Fator",
            orientation="h",
            color="Direção",
            color_discrete_map={home_team: "#F97316", away_team: "#38BDF8"},
        )
        factor_figure.update_layout(
            height=350,
            legend_title=None,
            xaxis_title="Contribuição para o modelo",
            yaxis_title=None,
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(factor_figure, use_container_width=True)

    with tab_simulation:
        simulated = simulate_score_distribution(
            prediction,
            bundle.residual_std_home,
            bundle.residual_std_away,
        )
        simulation_win_rate = float(simulated["home_win"].mean())
        st.metric(
            f"{home_team} venceu nas simulações",
            f"{simulation_win_rate:.1%}",
            "5.000 cenários",
        )
        histogram = go.Figure()
        histogram.add_trace(
            go.Histogram(
                x=simulated["margin"],
                nbinsx=35,
                marker_color="#F97316",
                opacity=0.85,
            )
        )
        histogram.add_vline(x=0, line_dash="dash", line_color="#F8FAFC")
        histogram.update_layout(
            height=340,
            xaxis_title=f"Margem: {home_team} − {away_team}",
            yaxis_title="Quantidade de simulações",
            margin=dict(l=10, r=10, t=25, b=10),
        )
        st.plotly_chart(histogram, use_container_width=True)

    with tab_model:
        model_metrics = bundle.metrics
        columns = st.columns(5)
        columns[0].metric("Accuracy", f"{model_metrics['accuracy']:.1%}")
        columns[1].metric("Log Loss", f"{model_metrics['log_loss']:.3f}")
        columns[2].metric("Brier Score", f"{model_metrics['brier_score']:.3f}")
        columns[3].metric("MAE casa", f"{model_metrics['home_points_mae']:.1f} pts")
        columns[4].metric("MAE visitante", f"{model_metrics['away_points_mae']:.1f} pts")
        st.caption(
            "Avaliação feita nos 20% finais da base em ordem cronológica. "
            "Depois da avaliação, o modelo é novamente treinado com todos os jogos."
        )

    with st.expander("Ver últimas partidas da base"):
        st.dataframe(
            games.sort_values("game_date", ascending=False).head(20),
            hide_index=True,
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
