from __future__ import annotations

import streamlit as st

from src.shot_storage import count_player_shots
from src.store import (
    DEFAULT_DB_PATH,
    count_distinct_players,
    count_distinct_teams,
    count_games,
    list_seasons,
    read_raw_games,
)
from src.ui import components, theme
from src.ui.formatters import format_int_br

st.set_page_config(
    page_title="NBA Analytics Lab",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject_base_style("overview")

components.page_header(
    "O jogo começa nos dados.",
    "Explore confrontos, descubra padrões e acompanhe suas projeções. Escolha uma análise para começar.",
    category="VISÃO GERAL",
)

real_data_available = DEFAULT_DB_PATH.exists() and count_games(DEFAULT_DB_PATH) > 0
last_updated = components.db_last_updated(DEFAULT_DB_PATH) if real_data_available else None
seasons = list_seasons(DEFAULT_DB_PATH) if real_data_available else []
seasons_label = f"{seasons[0]} a {seasons[-1]}" if len(seasons) > 1 else (seasons[0] if seasons else None)

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

if real_data_available:
    latest_game = read_raw_games(DEFAULT_DB_PATH)["game_date"].max()
    with st.container(border=True, key="coverage"):
        from src.ui.formatters import format_date_br
        from src.ui.navigation import page_link

        status, action = st.columns([3, 1])
        with status:
            st.markdown(f"**Cobertura do histórico: até {format_date_br(latest_game)}**")
            st.caption("A data da última partida pode ser diferente da data de atualização dos arquivos.")
        with action:
            page_link("data", "Gerenciar dados")

components.section_header("Escolha sua próxima análise", "Da rodada de hoje ao detalhe de cada jogador.")
for page_ids in (("games", "teams", "players"), ("shots", "season", "performance")):
    for column, page_id in zip(st.columns(3), page_ids, strict=True):
        with column:
            components.tool_card(page_id)

components.section_header("Conheça a base por trás das projeções")
for column, page_id in zip(st.columns(2), ("quality", "data"), strict=True):
    with column:
        components.tool_card(page_id)

if not real_data_available:
    components.note(
        "Nenhum dado real coletado ainda. Você pode explorar as páginas de times e "
        "jogadores com a base demonstrativa (sintética) — o seletor de fonte fica na "
        "seção 'Fonte e opções da análise' — ou ir até 'Dados e Atualizações' para coletar "
        "dados reais.",
        kind="warning",
    )
