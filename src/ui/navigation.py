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
    Page("overview", "app.py", "Início", ":material/home:", "EXPLORAR", "Sua rodada em um só lugar.", "/"),
    Page(
        "opportunities",
        "pages/9_Oportunidades.py",
        "Ao vivo",
        ":material/monitoring:",
        "EXPLORAR",
        "Forma atual, probabilidades condicionais e acompanhamento dos jogos.",
        "/Oportunidades",
    ),
    Page(
        "games",
        "pages/7_Jogos.py",
        "Jogos do dia",
        ":material/calendar_today:",
        "EXPLORAR",
        "Confrontos e destaques da rodada.",
        "/Jogos",
    ),
    Page(
        "picks",
        "pages/8_Palpites.py",
        "Palpites de hoje",
        ":material/auto_awesome:",
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
        "defense",
        "pages/12_Defesa.py",
        "Defesa dos times",
        ":material/shield:",
        "EXPLORAR",
        "Perímetro, garrafão, DRtg e cobertura dos indicadores.",
        "/Defesa",
    ),
    Page(
        "matchups",
        "pages/13_Marcacoes.py",
        "Marcações e encaixes",
        ":material/person_search:",
        "EXPLORAR",
        "Defensores por partida e produção contra perfis defensivos.",
        "/Marcacoes",
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
        "injuries",
        "pages/14_Lesoes.py",
        "Lesões e disponibilidade",
        ":material/healing:",
        "ACOMPANHAR",
        "Boletim de lesões com fonte, referência e atualização automática.",
        "/Lesoes",
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
        "archive",
        "pages/10_Historico_Diario.py",
        "Histórico diário",
        ":material/history:",
        "ACOMPANHAR",
        "Previsões pré-jogo preservadas e resultados de cada rodada.",
        "/Historico_Diario",
    ),
    Page(
        "research",
        "pages/11_Laboratorio.py",
        "Laboratório de modelos",
        ":material/science:",
        "ACOMPANHAR",
        "Bayes, XGBoost e métricas de impacto e tracking.",
        "/Laboratorio",
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
        primary = ("overview", "games", "picks", "opportunities", "archive")
        st.caption("SUA RODADA")
        for page_id in primary:
            prefix = "nav_active" if page_id == active_page else "nav_item"
            with st.container(key=f"{prefix}_{page_id}"):
                page_link(page_id)
        groups = {
            "Analisar jogadores e times": ("players", "teams", "defense", "matchups", "shots", "season"),
            "Resultados e modelo": ("performance", "quality", "research"),
            "Dados e disponibilidade": ("injuries", "data"),
        }
        for label, identifiers in groups.items():
            with st.expander(label, expanded=active_page in identifiers):
                for page_id in identifiers:
                    prefix = "nav_active" if page_id == active_page else "nav_item"
                    with st.container(key=f"{prefix}_{page_id}"):
                        page_link(page_id)
        st.caption("Projeção é uma estimativa. Confira participação, fonte e horário.")
