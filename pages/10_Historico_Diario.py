import streamlit as st

from src.live_types import EASTERN, utc_now
from src.store import DEFAULT_DB_PATH
from src.ui import components, theme
from src.ui.archive import archive_panel, request_archive_refresh

st.set_page_config(
    page_title="Histórico diário — NBA Analytics Lab", page_icon=":material/history:", layout="wide"
)
theme.inject_base_style("archive")
components.page_header(
    "A previsão de antes, preservada.",
    "Consulte os destaques que projetamos antes de cada partida e compare com o que aconteceu em quadra.",
    category="HISTÓRICO DIÁRIO",
)
request_archive_refresh(DEFAULT_DB_PATH)
day = st.date_input("Dia da rodada (calendário NBA)", value=utc_now().astimezone(EASTERN).date())
archive_panel(DEFAULT_DB_PATH, day.isoformat())
