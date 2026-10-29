import streamlit as st

from src.live_store import read_live_games
from src.live_types import EASTERN, utc_now
from src.store import DEFAULT_DB_PATH
from src.ui import components, theme
from src.ui.match_center import match_center
from src.ui.navigation import page_link

st.set_page_config(
    page_title="Central da partida — NBA Analytics Lab",
    page_icon=":material/sports_basketball:",
    layout="wide",
)
theme.inject_base_style("match_center")
components.page_header("Central da partida", "Placar, jogadores, disponibilidade e defesa no mesmo lugar.")
day = st.date_input("Dia NBA", value=utc_now().astimezone(EASTERN).date(), key="center_day")


@st.fragment(run_every=30)
def round_center():
    games = read_live_games(DEFAULT_DB_PATH, day.isoformat())
    if not games:
        st.info("Aguardando o calendário desta data. A coleta continua em segundo plano.")
        page_link("games", "Ver a rodada ou informar um confronto")
        return
    choices = {game.key: game for game in games}
    selected = st.selectbox(
        "Partida",
        list(choices),
        format_func=lambda k: f"{choices[k].away} × {choices[k].home}",
        key="center_matchup",
    )
    mode = st.segmented_control(
        "Ver na partida",
        ["Resumo", "Palpites", "Disponibilidade", "Defesa", "Ao vivo"],
        default="Resumo",
        required=True,
        key="center_view",
    )
    match_center(DEFAULT_DB_PATH, choices[selected], mode)


round_center()
