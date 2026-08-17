from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data import load_real_games
from src.model import train_models
from src.season_simulator import actual_final_standings, simulate_season
from src.store import DEFAULT_DB_PATH, list_seasons
from src.ui import components, states, theme

st.set_page_config(
    page_title="Temporada — NBA Analytics Lab",
    page_icon="🏆",
    layout="wide",
)

theme.inject_base_style()

st.markdown("## 🏆 Simulação de temporada")
st.caption(
    "Simulação de Monte Carlo do restante de uma temporada já coletada: "
    "probabilidade de classificação direta, Play-In e playoffs por time. "
    "Estimativas educacionais, não orientação de apostas."
)

if not DEFAULT_DB_PATH.exists() or not list_seasons(DEFAULT_DB_PATH):
    states.empty_state(
        "Nenhuma temporada coletada ainda",
        "Colete jogos reais antes de simular uma temporada.",
        actions=[
            ("Coletar dados", "rode 'python scripts/update_data.py' no terminal do projeto")
        ],
    )

components.source_badge("NBA API — dados reais", components.db_last_updated(DEFAULT_DB_PATH))


@st.cache_data(show_spinner=False)
def _load_games() -> pd.DataFrame:
    return load_real_games()


@st.cache_resource(show_spinner=False)
def _train(games: pd.DataFrame):
    return train_models(games)


games = _load_games()
bundle = _train(games)

st.markdown(
    '<div style="padding:12px 15px;border-left:4px solid #f97316;'
    'background:#151f32;border-radius:8px;color:#dbe4f3;">'
    "\"Restante da temporada\" aqui é um recorte de uma temporada já encerrada: "
    "os jogos depois da data de corte são reais, mas o placar deles é ignorado "
    "de propósito para simular o que aconteceria a partir daquele ponto. Isso "
    "permite comparar a previsão com o que realmente aconteceu.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Configuração")
    season = st.selectbox("Temporada", list_seasons(DEFAULT_DB_PATH))

    season_dates = games.loc[games["season"] == season, "game_date"]
    min_date, max_date = season_dates.min().date(), season_dates.max().date()
    default_cutoff = min_date + (max_date - min_date) * 0.7 if season_dates.size else min_date

    cutoff_date = st.date_input(
        "Simular a partir de",
        value=default_cutoff,
        min_value=min_date,
        max_value=max_date,
    )
    n_simulations = st.slider("Número de cenários simulados", 1_000, 20_000, 5_000, step=1_000)
    run_simulation = st.button("Rodar simulação", type="primary")

    st.divider()
    st.caption(
        "Este projeto produz estimativas esportivas educacionais. "
        "Não utiliza odds e não fornece orientação de apostas."
    )

if not run_simulation:
    st.info("Escolha a temporada e a data de corte na barra lateral e clique em 'Rodar simulação'.")
    st.stop()

with st.spinner(f"Simulando {n_simulations:,} cenários...".replace(",", ".")):
    try:
        summary = simulate_season(
            games, bundle, season, cutoff_date, n_simulations=n_simulations, seed=42
        )
    except ValueError as error:
        st.error(str(error))
        st.stop()

season_games = games["season"] == season
known_games_count = season_games.sum() - (
    games.loc[season_games, "game_date"] >= pd.Timestamp(cutoff_date)
).sum()
st.caption(
    f"{known_games_count} jogos conhecidos antes do corte, "
    f"{len(games[(games['season'] == season) & (games['game_date'] >= pd.Timestamp(cutoff_date))])} "
    "jogos restantes simulados por cenário."
)

tab_probabilities, tab_reveal = st.tabs(["Probabilidades", "O que realmente aconteceu"])

with tab_probabilities:
    for conference in sorted(summary["conference"].unique()):
        st.markdown(f"#### Conferência {conference}")
        conf_summary = summary[summary["conference"] == conference].sort_values(
            "prob_playoffs", ascending=False
        )

        figure = px.bar(
            conf_summary,
            x="prob_playoffs",
            y="team",
            orientation="h",
            text=conf_summary["prob_playoffs"].map(lambda value: f"{value:.0%}"),
            color_discrete_sequence=["#38BDF8"],
        )
        figure.update_traces(textposition="outside")
        figure.update_layout(
            height=380,
            xaxis_tickformat=".0%",
            xaxis_range=[0, 1],
            xaxis_title="Probabilidade de playoffs",
            yaxis_title=None,
            yaxis=dict(autorange="reversed"),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(figure, use_container_width=True)

        display = conf_summary[
            [
                "team",
                "current_wins",
                "projected_wins_mean",
                "projected_wins_p10",
                "projected_wins_p90",
                "prob_direct_playoffs",
                "prob_play_in",
                "prob_playoffs",
            ]
        ].rename(
            columns={
                "team": "Time",
                "current_wins": "Vitórias até o corte",
                "projected_wins_mean": "Vitórias finais (média)",
                "projected_wins_p10": "P10",
                "projected_wins_p90": "P90",
                "prob_direct_playoffs": "Prob. classif. direta",
                "prob_play_in": "Prob. Play-In",
                "prob_playoffs": "Prob. playoffs",
            }
        )
        st.dataframe(
            display.style.format(
                {
                    "Vitórias finais (média)": "{:.1f}",
                    "P10": "{:.0f}",
                    "P90": "{:.0f}",
                    "Prob. classif. direta": "{:.1%}",
                    "Prob. Play-In": "{:.1%}",
                    "Prob. playoffs": "{:.1%}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

with tab_reveal:
    st.caption(
        "Classificação real da temporada regular (jogos que realmente aconteceram). "
        "O status 'Play-In' aqui é apenas a faixa de posição (7ª–10ª) pelo saldo de "
        "vitórias — os jogos oficiais do mata-mata do Play-In não são coletados por "
        "este projeto, então o resultado exato dessas partidas não está disponível."
    )
    actual = actual_final_standings(games, season).drop(columns=["games"])
    comparison = actual.merge(
        summary[["team", "prob_playoffs"]], on="team", how="left"
    ).rename(
        columns={
            "team": "Time",
            "conference": "Conferência",
            "wins": "Vitórias reais",
            "losses": "Derrotas reais",
            "seed": "Posição real",
            "status": "Status real",
            "prob_playoffs": "Prob. playoffs simulada",
        }
    )
    st.dataframe(
        comparison.style.format({"Prob. playoffs simulada": "{:.1%}"}),
        hide_index=True,
        use_container_width=True,
    )
