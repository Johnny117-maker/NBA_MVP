from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.data_quality import bulletin_quality, collection_quality
from src.injuries import injury_snapshot
from src.live_store import get_state


def data_quality_panel(path: str | Path, *, detailed=False) -> None:
    _, state = injury_snapshot(path)
    bulletin = bulletin_quality(state)
    collection = collection_quality(get_state(path, "status", {}))
    with st.container(horizontal=True):
        for item in (collection, bulletin):
            st.badge(item["label"], color="green" if item["level"] == "current" else "orange")
    if bulletin["level"] == "blocked":
        st.warning(
            "Novos palpites individuais aguardam um boletim utilizável. O histórico original permanece salvo."
        )
    if detailed:
        st.caption(collection["reason"] + ". " + bulletin["reason"] + ".")
        st.caption(
            "Qualidade dos dados não é chance de acerto. Boletins recebidos há mais de 48 horas "
            "ou com referência de mais de dois dias suspendem novos palpites individuais. "
            "As consultas às fontes continuam sendo tentadas."
        )
