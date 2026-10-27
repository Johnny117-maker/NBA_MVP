from __future__ import annotations

import re
import time

import streamlit as st

from src.current_roster import current_nba_season
from src.nba_client import fetch_player_season_logs, fetch_season_games, pair_home_away
from src.shot_connector import fetch_player_shots
from src.shot_storage import count_player_shots, players_missing_shots, upsert_player_shots
from src.store import (
    DEFAULT_DB_PATH,
    count_distinct_players,
    count_distinct_teams,
    count_games,
    count_player_games,
    init_db,
    upsert_games,
    upsert_player_games,
)
from src.ui import components, states, theme
from src.ui.formatters import format_int_br

MAX_SHOT_BATCH = 30
SHOT_COLLECTION_DELAY_SECONDS = 0.6

st.set_page_config(
    page_title="Dados e Atualizações — NBA Analytics Lab",
    page_icon="🔄",
    layout="wide",
)

theme.inject_base_style("data")

components.page_header(
    "Uma boa análise começa na base.",
    "Colete partidas e jogadores por temporada e amplie sua base de arremessos em pequenos lotes.",
    category="DADOS E ATUALIZAÇÕES",
)

init_db(DEFAULT_DB_PATH)

components.source_badge("NBA API", components.db_last_updated(DEFAULT_DB_PATH))

components.metric_row(
    [
        {"label": "Jogos", "value": format_int_br(count_games(DEFAULT_DB_PATH))},
        {"label": "Times", "value": format_int_br(count_distinct_teams(DEFAULT_DB_PATH))},
        {"label": "Linhas de jogador", "value": format_int_br(count_player_games(DEFAULT_DB_PATH))},
        {"label": "Jogadores distintos", "value": format_int_br(count_distinct_players(DEFAULT_DB_PATH))},
        {"label": "Arremessos", "value": format_int_br(count_player_shots(DEFAULT_DB_PATH))},
    ]
)

tab_games, tab_shots, tab_advanced = st.tabs(["Jogos e jogadores", "Arremessos", "Coletas avançadas"])

with tab_games:
    components.section_header(
        "Atualizar uma temporada",
        "A coleta adiciona jogos e estatísticas individuais à base local. "
        "É necessário acesso aos serviços NBA.",
    )
    season_input = st.text_input(
        "Temporada (formato AAAA-AA, ex.: 2025-26)", value=current_nba_season(), key="season_to_collect"
    )
    st.caption("Você pode repetir uma coleta para buscar novos registros da mesma temporada.")
    if st.button("Coletar esta temporada", type="primary"):
        season_input = season_input.strip()
        if not re.fullmatch(r"\d{4}-\d{2}", season_input) or (
            int(season_input[-2:]) != (int(season_input[:4]) + 1) % 100
        ):
            st.error("Informe uma temporada válida, como 2025-26 ou 2026-27.")
            st.stop()
        progress = st.progress(0.0, text="Baixando jogos...")
        try:
            raw_games = fetch_season_games(season_input)
            games = pair_home_away(raw_games)
            added_games = upsert_games(games, DEFAULT_DB_PATH)
            progress.progress(0.5, text="Baixando jogadores...")

            player_raw = fetch_player_season_logs(season_input)
            added_players = upsert_player_games(player_raw, DEFAULT_DB_PATH)
            progress.progress(1.0, text="Concluído.")

            st.success(
                f"{added_games} jogos novos e {added_players} linhas de jogador novas "
                f"gravadas para a temporada {season_input}."
            )
            st.rerun()
        except Exception as error:  # nba_api costuma falhar por timeout/bloqueio de rede
            progress.empty()
            states.error_state(f"Falha ao coletar a temporada {season_input}.", detail=str(error))

with tab_shots:
    pending = players_missing_shots(DEFAULT_DB_PATH)
    if not pending:
        st.success(
            "Nenhum jogador pendente — todo mundo que já tem jogos coletados também "
            "já tem arremessos coletados."
        )
    else:
        st.markdown(
            f"**{format_int_br(len(pending))} pares jogador-temporada** ainda sem "
            "arremessos coletados. Uma chamada por jogador por temporada — mais lento "
            "que a aba de jogos; para coletar centenas de uma vez, prefira o terminal:"
        )
        st.code("python scripts/update_shots.py", language="powershell")

        batch_size = st.slider(
            "Quantos jogadores coletar agora?", 1, min(MAX_SHOT_BATCH, len(pending)), min(10, len(pending))
        )
        if st.button("Coletar arremessos"):
            batch = pending[:batch_size]
            progress = st.progress(0.0)
            status = st.empty()
            collected, failed = 0, 0

            for index, (player_id, player_name, season) in enumerate(batch, start=1):
                status.caption(f"[{index}/{len(batch)}] {player_name} ({season})...")
                try:
                    shots = fetch_player_shots(player_id, season)
                    upsert_player_shots(shots, DEFAULT_DB_PATH)
                    collected += 1
                except Exception:  # nba_api costuma falhar por timeout/bloqueio de rede
                    failed += 1
                progress.progress(index / len(batch))
                time.sleep(SHOT_COLLECTION_DELAY_SECONDS)

            status.empty()
            progress.empty()
            st.success(f"{collected} jogadores coletados, {failed} falharam nesta execução.")
            st.rerun()

with tab_advanced:
    components.section_header(
        "Estatísticas avançadas", "Coletas maiores disponíveis pelo terminal do projeto."
    )
    st.caption(
        "Ratings oficiais e titularidade exigem uma consulta por partida. "
        "Escolha a temporada nos comandos antes de executar."
    )
    st.code(
        "python scripts/update_advanced_stats.py --seasons 2025-26\n"
        "python scripts/update_starter_status.py --seasons 2025-26",
        language="powershell",
    )
