from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.injuries import injury_snapshot
from src.ui.navigation import page_link


@st.fragment(run_every=30)
def watch_pick_injuries(path: str | Path) -> None:
    rows, state = injury_snapshot(path)
    version = (state.get("source"), tuple(sorted(zip(rows.player, rows.status, strict=True))))
    key = "_pick_injury_version:" + str(Path(path).resolve())
    previous = st.session_state.get(key)
    st.session_state[key] = version
    if previous is not None and previous != version:
        st.rerun()


@st.fragment(run_every=60)
def injury_notice(path: str | Path) -> None:
    rows, state = injury_snapshot(path)
    if not state.get("source"):
        st.caption("Boletim de lesões aguardando a primeira consulta. Destaques não confirmam participação.")
    else:
        st.caption(
            f"Lesões: {len(rows)} atletas no boletim · {state['source']} · "
            f"referência {state.get('source_as_of', 'não informada')}"
            + (" · informação defasada" if state.get("stale") else "")
        )
    page_link("injuries", "Consultar lesões e disponibilidade")


def annotate_injuries(table: pd.DataFrame, path: str | Path, team: str) -> pd.DataFrame:
    from src.entity_ids import normalized_name

    rows, state = injury_snapshot(path)
    result = table.copy()
    lookup = {normalized_name(row.player): row.status for row in rows.loc[rows.team.eq(team)].itertuples()}
    result["Boletim de lesões"] = result["Jogador"].map(
        lambda name: (
            lookup.get(normalized_name(name), "Sem registro no boletim")
            if state.get("source")
            else "Consulta indisponível"
        )
    )
    if state.get("stale"):
        result["Boletim de lesões"] += " · defasado"
    return result
