from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.live_store import get_state


def learning_status(path: str | Path, *, detailed: bool = False) -> None:
    local = get_state(path, "props_feedback", {})
    remote = get_state(path, "remote_learning_status", {})
    report = max((local, remote), key=lambda item: (item.get("before_day", ""), item.get("rows", 0)))
    st.caption("Aprendizado dos jogadores: " + report.get("status", "Aguardando resultados confirmados"))
    if not detailed:
        return
    st.write(
        "Após os jogos, o sistema compara a previsão salva com o resultado real. "
        "Novos boxscores entram no próximo treino do XGBoost. Os erros recentes também podem "
        "ajustar a combinação com Bayes e corrigir desvios de pontos, rebotes e assistências."
    )
    st.caption(
        "Cada ajuste exige pelo menos 120 resultados por estatística e 8 datas. "
        "É aplicado apenas quando reduz o erro em pelo menos 2% e 0,02 unidade em datas "
        "posteriores às usadas no ajuste. Partidas sem participação não contam como zero. "
        "As probabilidades Over/Under continuam experimentais."
    )
    if not report:
        st.info("O sistema ainda está aguardando a comparação das primeiras previsões com os resultados.")
        return
    st.caption(
        f"{report.get('dates', 0)} datas avaliadas · "
        f"{report.get('rows', 0)} comparações PTS/REB/AST · "
        f"resultados até {report.get('through_day') or 'ainda não disponíveis'}."
    )
    labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}
    rows = [
        {
            "Estatística": labels.get(stat, stat),
            "Situação": values["status"],
            "Resultados": values["rows"],
            "Erro anterior": values.get("base_mae"),
            "Erro do ajuste": values.get("candidate_mae"),
        }
        for stat, values in report.get("stats", {}).items()
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Validação dos ajustes pelos resultados reais")
    with st.expander("Auditoria do aprendizado"):
        st.json(report, expanded=False)
