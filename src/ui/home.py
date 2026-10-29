from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.analysis_archive import read_snapshots
from src.live_store import get_state, read_live_games
from src.live_types import EASTERN, utc_now
from src.ui.data_quality import data_quality_panel
from src.ui.learning import learning_status
from src.ui.navigation import page_link


@st.fragment(run_every=30)
def today_overview(path: str | Path) -> None:
    day = utc_now().astimezone(EASTERN).date().isoformat()
    games = read_live_games(path, day)
    snapshots = read_snapshots(path, day)
    columns = st.columns(3)
    columns[0].metric("Jogos hoje", len(games) if games else "Aguardando calendário")
    columns[1].metric("Ao vivo agora", sum(game.state == "live" for game in games))
    columns[2].metric("Jogos com previsão salva", len(snapshots))
    status = get_state(path, "status", {})
    stamp = status.get("live_success_at") or status.get("archive_success_at")
    if stamp:
        updated = pd.Timestamp(stamp).tz_convert("America/Sao_Paulo")
        st.caption(f"Dados consultados em {updated:%d/%m às %H:%M} · horário de Brasília")
    else:
        st.caption("Aguardando a atualização do calendário. A coleta acontece em segundo plano.")
    if games:
        preview = []
        for game in games:
            label = {"pre": "Vai começar", "live": "Ao vivo", "final": "Encerrado"}.get(
                game.state, "A conferir"
            )
            time = (
                pd.Timestamp(game.kickoff).tz_convert("America/Sao_Paulo").strftime("%H:%M")
                if game.kickoff
                else "—"
            )
            preview.append(
                {"Jogo": f"{game.away} × {game.home}", "Horário de Brasília": time, "Situação": label}
            )
        st.dataframe(pd.DataFrame(preview), hide_index=True, alt="Jogos de hoje, horários e situação")
    with st.container(horizontal=True):
        page_link("picks", "Ver palpites de hoje")
        page_link("match_center", "Analisar um jogo")
        page_link("archive", "Conferir previsões e resultados")
    learning_status(path)
    data_quality_panel(path)
