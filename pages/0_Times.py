from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data import (
    load_games,
    team_snapshot,
)
from src.model import predict_game, train_models
from src.store import DEFAULT_DB_PATH, count_games
from src.ui import components, teams_sections, theme
from src.ui.insights import matchup_intel

st.set_page_config(
    page_title="Times — NBA Analytics Lab",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject_base_style("teams")


@st.cache_data(show_spinner=False)
def demo_games() -> pd.DataFrame:
    return load_games()


@st.cache_resource(show_spinner=False, max_entries=2)
def cached_train(games: pd.DataFrame):
    return train_models(games)


def main() -> None:
    components.page_header(
        "O confronto, em perspectiva.",
        "Compare a forma das equipes, explore os fatores e veja a faixa de placares estimada.",
        category="TIMES",
    )

    real_data_available = DEFAULT_DB_PATH.exists() and count_games(DEFAULT_DB_PATH) > 0
    source, uploaded_file = teams_sections.source_options_panel(real_data_available)
    games, bundle, is_demo, last_updated = teams_sections.load_games_and_train(
        source, uploaded_file, demo_games, cached_train
    )

    components.source_badge(source, last_updated)
    if is_demo:
        components.note("Os números desta tela são sintéticos e não representam a temporada atual da NBA.")

    home_team, away_team, home_rest, away_rest = teams_sections.matchup_picker(games)
    home = team_snapshot(games, home_team)
    away = team_snapshot(games, away_team)
    prediction = predict_game(bundle, home, away, home_rest, away_rest)

    components.section_header("Central da partida", "Forma recente, força das equipes e pontuação observada.")
    matchup_intel(games, away_team, home_team, key="teams")

    teams_sections.scenario_summary(prediction, games, home_team, away_team)
    teams_sections.register_prediction_button(prediction, home_team, away_team)
    teams_sections.probability_and_interval(prediction, home_team, away_team)

    tab_analysis, tab_factors, tab_simulation, tab_model = st.tabs(
        ["Comparativo", "Fatores", "Simulação", "Qualidade do modelo"]
    )
    with tab_analysis:
        teams_sections.comparison_tab(games, home, away, home_team, away_team)
    with tab_factors:
        teams_sections.factors_tab(prediction, home_team, away_team)
    with tab_simulation:
        teams_sections.simulation_tab(prediction, bundle, home_team, away_team)
    with tab_model:
        teams_sections.model_quality_tab(bundle)
    teams_sections.recent_games_expander(games)


if __name__ == "__main__":
    main()
