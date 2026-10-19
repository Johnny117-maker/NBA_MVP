from __future__ import annotations

import time

import streamlit as st

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

theme.inject_base_style()

st.markdown("## 🔄 Dados e Atualizações")
st.caption(
    "Coleta de dados reais via nba_api, separada das páginas de análise (seção 3 do "
    "planejamento de UI/UX: atualização não deve se misturar com exploração). Coletas "
    "grandes ainda são melhor feitas pelo terminal, em segundo plano — esta página "
    "cobre lotes pequenos direto na interface."
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

tab_games, tab_shots = st.tabs(["Jogos e jogadores (por temporada)", "Arremessos (incremental)"])

with tab_games:
    st.markdown(
        "Baixa o log de jogos e de jogadores de uma temporada inteira em poucas "
        "chamadas (uma para os jogos da liga toda, uma para os jogadores da liga "
        "toda) — rápido, roda direto aqui, sem precisar do terminal."
    )
    season_input = st.text_input(
        "Temporada (formato AAAA-AA, ex.: 2025-26)", value="2025-26", key="season_to_collect"
    )
    if st.button("Coletar esta temporada"):
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
            states.error_state(
                f"Falha ao coletar a temporada {season_input}.", detail=str(error)
            )

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

st.divider()
st.markdown("#### Coletas avançadas (só pelo terminal, por enquanto)")
st.caption(
    "Rating oficial (Offensive/Defensive Rating) e titularidade real exigem uma "
    "chamada por jogo — muito mais lento que as coletas acima, ainda não trazido "
    "para dentro da interface:"
)
st.code(
    "python scripts/update_advanced_stats.py --seasons 2024-25\n"
    "python scripts/update_starter_status.py --seasons 2024-25",
    language="powershell",
)
