import streamlit as st

from src.store import DEFAULT_DB_PATH
from src.ui import components, theme
from src.ui.live import opportunities_panel

st.set_page_config(
    page_title="Over / Under — NBA Analytics Lab", page_icon=":material/monitoring:", layout="wide"
)
theme.inject_base_style("opportunities")
components.page_header(
    "A forma atual, dentro de cada partida.",
    "Acompanhe pontos, rebotes e assistências e compare linhas antes e durante o jogo.",
    category="OVER / UNDER",
)
opportunities_panel(DEFAULT_DB_PATH)
