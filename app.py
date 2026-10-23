from __future__ import annotations

import streamlit as st

from src.shot_storage import count_player_shots
from src.store import (
    DEFAULT_DB_PATH,
    count_distinct_players,
    count_distinct_teams,
    count_games,
    list_seasons,
)
from src.ui import components, theme
from src.ui.formatters import format_int_br

st.set_page_config(
    page_title="NBA Analytics Lab",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject_base_style()

st.markdown(
    """
    <div class="hero">
        <h1>🏀 NBA Analytics Lab</h1>
        <p>Análise de times e jogadores, projeções experimentais e explicação dos fatores do modelo.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.caption(
        "Este projeto produz estimativas esportivas educacionais. "
        "Não utiliza odds e não fornece orientação de apostas."
    )

real_data_available = DEFAULT_DB_PATH.exists() and count_games(DEFAULT_DB_PATH) > 0
last_updated = components.db_last_updated(DEFAULT_DB_PATH) if real_data_available else None
seasons = list_seasons(DEFAULT_DB_PATH) if real_data_available else []
seasons_label = (
    f"{seasons[0]} a {seasons[-1]}" if len(seasons) > 1 else (seasons[0] if seasons else None)
)

components.source_badge(
    "NBA API — dados reais" if real_data_available else "Nenhum dado real coletado ainda",
    last_updated,
    seasons=seasons_label,
)

components.metric_row(
    [
        {"label": "Jogos analisados", "value": format_int_br(count_games(DEFAULT_DB_PATH))},
        {"label": "Times cadastrados", "value": format_int_br(count_distinct_teams(DEFAULT_DB_PATH))},
        {"label": "Jogadores coletados", "value": format_int_br(count_distinct_players(DEFAULT_DB_PATH))},
        {"label": "Temporadas", "value": format_int_br(len(seasons))},
        {"label": "Arremessos coletados", "value": format_int_br(count_player_shots(DEFAULT_DB_PATH))},
    ]
)

st.markdown("#### Comece por aqui")
action_cols = st.columns(5)
with action_cols[0]:
    st.page_link("pages/0_Times.py", label="Analisar times", icon="🏀")
with action_cols[1]:
    st.page_link("pages/1_Jogadores.py", label="Analisar jogadores", icon="🧮")
with action_cols[2]:
    st.page_link("pages/4_Mapa_Arremessos.py", label="Mapa de arremessos", icon="🎯")
with action_cols[3]:
    st.page_link("pages/5_Dados_Atualizacoes.py", label="Atualizar dados", icon="🔄")
with action_cols[4]:
    st.page_link("pages/7_Jogos_do_Dia.py", label="Jogos do dia", icon="📅")

if not real_data_available:
    components.note(
        "Nenhum dado real coletado ainda. Você pode explorar as páginas de times e "
        "jogadores com a base demonstrativa (sintética) — o seletor de fonte fica na "
        "barra lateral de cada página — ou ir até 'Dados e Atualizações' para coletar "
        "dados reais.",
        kind="warning",
    )
