from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ui import components, states, theme  # noqa: E402

theme.inject_base_style()

components.source_badge(
    "NBA API — dados reais", pd.Timestamp("2026-08-16 14:30"), seasons="2023-24 a 2025-26"
)
components.note("Nota informativa de teste.", kind="info")
components.metric_row(
    [
        {"label": "Jogos", "value": "1.230"},
        {"label": "Times", "value": "30"},
        {"label": "Jogadores", "value": "184"},
        {"label": "Temporadas", "value": "3"},
        {"label": "Extra 1", "value": "1"},
        {"label": "Extra 2", "value": "2"},
        {"label": "Sétimo item", "value": "7"},
    ]
)
components.sample_size_caption(18, 74)

states.small_sample_warning(4, threshold=15)
states.stale_data_notice(pd.Timestamp.now() - pd.DateOffset(days=9), days_threshold=7)
states.error_state("Falha ao atualizar.", detail="timeout")

st.text_input("Filtro de teste", key="algum_filtro", value="valor inicial")
components.clear_filters_button(["algum_filtro"], label="Limpar filtros")
st.write(f"Valor atual: {st.session_state.get('algum_filtro', '(vazio)')}")

persistent_choice = components.persistent_selectbox(
    "Jogador de teste", ["Ana", "Beto", "Carla"], query_key="jogador_teste"
)
st.write(f"Selecionado: {persistent_choice}")

if st.checkbox("Mostrar estado vazio", key="show_empty"):
    states.empty_state(
        "Nenhum dado ainda",
        "Descrição do estado vazio.",
        actions=[("Carregar demo", "clica em algo"), ("Buscar dados reais", "roda o script")],
    )
    st.write("NÃO deveria aparecer")
