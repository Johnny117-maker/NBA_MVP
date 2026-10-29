from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.analysis_archive import read_snapshots
from src.injuries import current_pick_players
from src.live_types import utc_now
from src.ui.navigation import page_link


def saved_picks_panel(path: str | Path, day: str, games: pd.DataFrame) -> bool:
    allowed = {
        f"{day}:{row.home_team_tricode}:{row.away_team_tricode}" for row in games.itertuples(index=False)
    }
    rows = []
    for snapshot in read_snapshots(path, day):
        if snapshot["game_key"] not in allowed or pd.Timestamp(snapshot["kickoff"]) <= utc_now():
            continue
        for player in snapshot["players"]:
            rows.append(
                {
                    "player_name": player["name"],
                    "Jogador": player["name"],
                    "Time": player["team"],
                    "Jogo": f"{snapshot['away']} × {snapshot['home']}",
                    "Pontos": round(player["stats"]["pts"]["projected"], 1),
                    "Rebotes": round(player["stats"]["reb"]["projected"], 1),
                    "Assistências": round(player["stats"]["ast"]["projected"], 1),
                }
            )
    table = current_pick_players(path, pd.DataFrame(rows)) if rows else pd.DataFrame()
    if table.empty:
        return False
    st.subheader("Projeções prontas para hoje")
    st.caption(
        "Estimativas salvas antes dos jogos. Lesões e dúvidas são filtradas pelo boletim atual. "
        "A ausência no boletim não confirma participação."
    )
    games_filter = st.selectbox(
        "Filtrar por jogo", ["Todos", *sorted(table.Jogo.unique())], key="saved_pick_game"
    )
    if games_filter != "Todos":
        table = table.loc[table.Jogo.eq(games_filter)]
    st.dataframe(
        table.sort_values("Pontos", ascending=False).drop(columns="player_name"),
        hide_index=True,
        alt="Pontos, rebotes e assistências previstos para os jogadores disponíveis",
    )
    with st.expander("Como ler estas projeções"):
        st.write(
            "Pontos, rebotes e assistências mostram a produção final estimada caso o atleta participe. "
            "Over significa mais que uma linha; Under significa menos. A linha estatística do sistema "
            "é uma referência e pode ser diferente da linha de uma casa."
        )
        st.caption("O histórico preserva a previsão original, mesmo quando a disponibilidade muda depois.")
        page_link("archive", "Ver faixas, detalhes e resultados")
    return True
