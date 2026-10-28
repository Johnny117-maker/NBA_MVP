from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Page:
    id: str
    path: str
    label: str
    icon: str
    group: str
    description: str
    route: str


PAGES = (
    Page("overview", "app.py", "Visão geral", "🏠", "EXPLORAR", "O ponto de partida das suas análises.", "/"),
    Page(
        "opportunities", "pages/9_Oportunidades.py", "Over / Under ao vivo", ":material/monitoring:",
        "EXPLORAR", "Forma atual, probabilidades condicionais e acompanhamento dos jogos.", "/Oportunidades",
    ),
    Page(
        "games",
        "pages/7_Jogos.py",
        "Jogos do dia",
        "📅",
        "EXPLORAR",
        "Confrontos e destaques da rodada.",
        "/Jogos",
    ),
    Page(
        "picks",
        "pages/8_Palpites.py",
        "Palpites de hoje",
        "✨",
        "EXPLORAR",
        "Tendências dos confrontos e projeções dos destaques de hoje.",
        "/Palpites",
    ),
    Page(
        "teams",
        "pages/0_Times.py",
        "Times",
        "🏀",
        "EXPLORAR",
        "Compare equipes e projete um confronto.",
        "/Times",
    ),
    Page(
        "players",
        "pages/1_Jogadores.py",
        "Jogadores",
        "👤",
        "EXPLORAR",
        "Perfil, evolução e projeções.",
        "/Jogadores",
    ),
    Page(
        "shots",
        "pages/4_Mapa_Arremessos.py",
        "Mapa de arremessos",
        "🎯",
        "EXPLORAR",
        "Explore a quadra e a eficiência por zona.",
        "/Mapa_Arremessos",
    ),
    Page(
        "season",
        "pages/2_Temporada.py",
        "Temporada",
        "🏆",
        "ACOMPANHAR",
        "Simule a classificação de uma temporada.",
        "/Temporada",
    ),
    Page(
        "performance",
        "pages/3_Desempenho.py",
        "Desempenho",
        "📈",
        "ACOMPANHAR",
        "Compare previsões salvas com resultados reais.",
        "/Desempenho",
    ),
    Page(
        "quality",
        "pages/6_Qualidade_Modelo.py",
        "Qualidade do modelo",
        "📊",
        "ACOMPANHAR",
        "Entenda os erros e limites das estimativas.",
        "/Qualidade_Modelo",
    ),
    Page(
        "data",
        "pages/5_Dados_Atualizacoes.py",
        "Dados e atualizações",
        "🔄",
        "GERENCIAR",
        "Mantenha a base de análise atualizada.",
        "/Dados_Atualizacoes",
    ),
)
PAGE_BY_ID = {page.id: page for page in PAGES}


def page_link(page_id: str, label: str | None = None) -> None:
    page = PAGE_BY_ID[page_id]
    try:
        st.page_link(str(ROOT / page.path), label=label or page.label, icon=page.icon, help=page.description)
    except StreamlitAPIException:
        # Permite abrir uma página diretamente, fora do ponto de entrada app.py.
        st.markdown(
            f'<a class="fallback-link" href="{page.route}" target="_self">'
            f"{page.icon} {escape(label or page.label)}</a>",
            unsafe_allow_html=True,
        )


def sidebar_navigation(active_page: str) -> None:
    with st.sidebar:
        st.markdown(
            '<div class="app-brand"><span class="brand-mark">N</span>'
            "<div><strong>NBA ANALYTICS</strong><span>LAB · ESTATÍSTICA EM JOGO</span></div></div>",
            unsafe_allow_html=True,
        )
        for group in ("EXPLORAR", "ACOMPANHAR", "GERENCIAR"):
            st.markdown(f'<p class="nav-group">{group}</p>', unsafe_allow_html=True)
            for page in PAGES:
                if page.group == group:
                    prefix = "nav_active" if page.id == active_page else "nav_item"
                    with st.container(key=f"{prefix}_{page.id}"):
                        page_link(page.id)
        st.divider()
        st.caption("Estimativas experimentais. Consulte a fonte, a data e a linha de cada análise.")
