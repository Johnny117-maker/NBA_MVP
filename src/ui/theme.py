from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

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

_STYLE_PATH = Path(__file__).with_name("styles.css")


def inject_base_style(active_page: str | None = None) -> None:
    st.markdown(_STYLE_PATH.read_text(encoding="utf-8"), unsafe_allow_html=True)
    pio.templates["nba_analytics"] = go.layout.Template(
        layout={
            "font": {"family": "Segoe UI, Arial, sans-serif", "size": 13, "color": COLORS["text_secondary"]},
            "colorway": [COLORS["accent"], COLORS["info"], "#a78bfa", "#fbbf24", "#94a3b8"],
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "xaxis": {"gridcolor": "#253044", "zerolinecolor": "#39455a"},
            "yaxis": {"gridcolor": "#253044", "zerolinecolor": "#39455a"},
            "hoverlabel": {"bgcolor": "#1a263a", "font_size": 13},
            "legend": {"bgcolor": "rgba(0,0,0,0)"},
        }
    )
    pio.templates.default = "plotly_dark+nba_analytics"
    if active_page is not None:
        from .navigation import sidebar_navigation

        sidebar_navigation(active_page)
