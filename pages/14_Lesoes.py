from __future__ import annotations

import pandas as pd
import streamlit as st

from src.injuries import STATUS, injury_snapshot, refresh_injuries
from src.live_types import current_season
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
from src.store import DEFAULT_DB_PATH
from src.ui import components, theme

st.set_page_config(
    page_title="Lesões e disponibilidade — NBA Analytics Lab", page_icon=":material/healing:", layout="wide"
)
theme.inject_base_style("injuries")
components.page_header(
    "Quem pode entrar em quadra.",
    "Boletim público de lesões, dúvidas e estimativas de retorno.",
    category="LESÕES",
)
st.caption(
    "Consulta automática a cada 5 minutos enquanto o sistema estiver aberto. "
    "A tela confere os dados salvos a cada minuto. O retorno estimado não confirma participação."
)
if st.button("Atualizar boletim agora", icon=":material/refresh:"):
    with st.spinner("Consultando as fontes públicas…"):
        refresh_injuries(DEFAULT_DB_PATH, force=True)


@st.fragment(run_every=60)
def bulletin():
    rows, state = injury_snapshot(DEFAULT_DB_PATH)
    if not state.get("source"):
        st.warning(
            "Nenhum boletim válido foi recebido. A ausência de dados não confirma atletas disponíveis."
        )
        if state.get("errors"):
            st.caption("Última tentativa: " + " · ".join(state["errors"]))
    else:
        st.caption(f"Fonte: {state['source']} · Referência: {state.get('source_as_of', '—')}")
        if state.get("daily_snapshot"):
            st.info(
                "Esta fonte fornece um snapshot diário. A consulta de 5 minutos verifica novas publicações; "
                "o intervalo de publicação da fonte pode ser maior."
            )
        if state.get("stale") or state.get("available") is False:
            st.warning(
                "O último boletim válido foi preservado e pode estar defasado. "
                "Confira a referência e o boletim oficial antes da partida."
            )
        if state.get("source_url"):
            st.link_button("Abrir fonte deste boletim", state["source_url"])
    if state.get("checked_at"):
        checked = pd.Timestamp(state["checked_at"]).tz_convert("America/Sao_Paulo")
        st.caption("Última consulta: " + checked.strftime("%d/%m/%Y %H:%M") + " · Brasília")
    components.metric_row(
        [
            {"label": "Atletas no boletim", "value": str(len(rows))},
            {
                "label": "Fora / reserva por lesão",
                "value": str(int(rows.status.isin(["Fora", "Reserva por lesão"]).sum())),
            },
            {
                "label": "Dia a dia / questionáveis",
                "value": str(int(rows.status.isin(["Dia a dia", "Questionável"]).sum())),
            },
            {"label": "Times com registros", "value": str(rows.team.nunique())},
        ]
    )
    left, right = st.columns(2)
    teams = left.multiselect(
        "Filtrar times",
        sorted(TEAM_ABBREVIATION_TO_NAME),
        format_func=lambda code: TEAM_ABBREVIATION_TO_NAME[code],
        key="injury_teams",
    )
    statuses = right.multiselect(
        "Filtrar status", sorted(set(STATUS.values()) | {"Não classificado"}), key="injury_statuses"
    )
    search = st.text_input("Buscar jogador", placeholder="Ex.: Jalen Brunson", key="injury_search")
    selected = rows.copy()
    if teams:
        selected = selected.loc[selected.team.isin(teams)]
    if statuses:
        selected = selected.loc[selected.status.isin(statuses)]
    if search.strip():
        selected = selected.loc[selected.player.str.contains(search.strip(), case=False, regex=False)]
    if selected.empty:
        st.info("Nenhum registro neste filtro." if state.get("source") else "Aguardando um boletim válido.")
        return
    st.dataframe(
        selected.sort_values(["team", "player"])[
            ["team", "player", "position", "status", "injury", "reported_at", "estimated_return", "note"]
        ],
        hide_index=True,
        height=560,
        column_config={
            "team": "Time",
            "player": "Jogador",
            "position": "Posição",
            "status": "Situação",
            "injury": "Lesão / motivo informado",
            "reported_at": "Data da informação",
            "estimated_return": "Retorno estimado pela fonte",
            "note": "Nota da fonte (original)",
        },
        alt="Boletim de lesões com situação, motivo, data da informação e estimativa de retorno.",
    )
    st.download_button(
        "Exportar boletim filtrado",
        selected.to_csv(index=False).encode("utf-8-sig"),
        "boletim_lesoes.csv",
        "text/csv",
    )


bulletin()
st.link_button(
    "Boletim oficial da NBA", f"https://official.nba.com/nba-injury-report-{current_season()}-season/"
)
st.caption(
    "Não constar na lista não confirma participação. "
    "Identificadores ESPN são mantidos separados dos IDs NBA. "
    "Os modelos não recebem uma alteração automática de probabilidade com base neste boletim."
)
