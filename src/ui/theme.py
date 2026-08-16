from __future__ import annotations

import streamlit as st

# Paleta já em uso em `.streamlit/config.toml` e no CSS inline de `app.py`
# (seção 16 do planejamento de UI/UX) — centralizada aqui em vez de
# redeclarada em cada página.
COLORS = {
    "background": "#0B1120",
    "surface": "#151F32",
    "border": "#263247",
    "accent": "#F97316",
    "info": "#38BDF8",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "text": "#F8FAFC",
    "text_secondary": "#B8C2D6",
}

# Cor de destaque por tipo de nota/selo (seções 5 e 13) — mapeada para as
# cores semânticas da paleta em vez de cores literais espalhadas pelo código.
_NOTE_BORDER_COLOR = {
    "info": COLORS["accent"],
    "warning": COLORS["warning"],
    "danger": COLORS["danger"],
    "success": COLORS["success"],
}

_BASE_STYLE = f"""
<style>
.block-container {{padding-top: 1.4rem; padding-bottom: 3rem;}}
[data-testid="stMetric"] {{
    background: linear-gradient(145deg, {COLORS["surface"]}, #111827);
    border: 1px solid {COLORS["border"]};
    border-radius: 14px;
    padding: 16px;
}}
.hero {{
    padding: 22px 26px;
    border: 1px solid {COLORS["border"]};
    border-radius: 18px;
    background: linear-gradient(120deg, #111827 0%, #172033 60%, #2a180d 100%);
    margin-bottom: 18px;
}}
.hero h1 {{margin: 0; font-size: 2.15rem;}}
.hero p {{color: {COLORS["text_secondary"]}; margin: 8px 0 0 0;}}
.app-note {{
    padding: 12px 15px;
    border-radius: 8px;
    background: {COLORS["surface"]};
    color: {COLORS["text"]};
    margin-bottom: 12px;
}}
.app-note--info {{border-left: 4px solid {_NOTE_BORDER_COLOR["info"]};}}
.app-note--warning {{border-left: 4px solid {_NOTE_BORDER_COLOR["warning"]};}}
.app-note--danger {{border-left: 4px solid {_NOTE_BORDER_COLOR["danger"]};}}
.app-note--success {{border-left: 4px solid {_NOTE_BORDER_COLOR["success"]};}}
.source-badge {{
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.85rem;
    border: 1px solid {COLORS["border"]};
    color: {COLORS["text_secondary"]};
    background: {COLORS["surface"]};
    margin-bottom: 10px;
}}
</style>
"""


def inject_base_style() -> None:
    """CSS compartilhado por todas as páginas — cartões, hero, notas, selo de fonte.

    Chame uma vez perto do topo de cada página (`app.py` e cada `pages/*.py`),
    depois de `st.set_page_config`. Substitui o bloco de CSS que antes era
    copiado e colado em cada arquivo.
    """
    st.markdown(_BASE_STYLE, unsafe_allow_html=True)
