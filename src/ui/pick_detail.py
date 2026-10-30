from __future__ import annotations

import pandas as pd
import streamlit as st

from src.prop_explanations import compare_line


def pick_detail(snapshot: dict, player: dict, *, key: str) -> None:
    key = f"{key}_{snapshot.get('game_id', '')}_{snapshot['captured_at']}_{player['name']}"
    labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}
    st.subheader(player["name"])
    stamp = pd.Timestamp(snapshot["captured_at"]).tz_convert("America/Sao_Paulo")
    st.caption(f"{snapshot['away']} × {snapshot['home']} · captura de {stamp:%d/%m às %H:%M} · Brasília")
    stat = st.segmented_control(
        "Analisar produção",
        list(labels),
        format_func=lambda s: labels[s],
        default="pts",
        required=True,
        key=key + "_stat",
    )
    estimate = player["stats"][stat]
    columns = st.columns(3)
    columns[0].metric(labels[stat] + " previstos", f"{estimate['projected']:.1f}")
    columns[1].metric(
        "Faixa provável P10–P90",
        f"{estimate['low']:.0f}–{estimate['high']:.0f}"
        if all(k in estimate for k in ("low", "high"))
        else "—",
    )
    columns[2].metric(
        "Minutos estimados", f"{player['minutes']:.1f}" if player.get("minutes") is not None else "—"
    )
    st.caption("A faixa é experimental e não garante o resultado. A projeção assume participação do atleta.")
    line = st.number_input(
        "Linha para comparar",
        min_value=0.0,
        max_value=200.0,
        value=float(estimate.get("line", int(estimate["projected"]) + 0.5)),
        step=0.5,
        key=key + "_line_" + stat,
    )
    probability = compare_line(estimate, line)
    if probability is None:
        st.info("Esta captura antiga não preservou os parâmetros para recalcular outras linhas.")
    else:
        columns = st.columns(3)
        for column, field, label in zip(
            columns,
            ("over", "under", "push"),
            ("Mais que a linha", "Menos que a linha", "Empate na linha"),
            strict=True,
        ):
            column.metric(label, f"{probability[field]:.1%}")
    st.caption("Referência estatística; a comparação não é cotação de casa nem modifica a captura original.")
    st.markdown("**O que sabemos antes do jogo**")
    factors = player.get("factors", {})
    recent = factors.get("recent", {}).get(stat, {})
    if recent.get("last5") is not None:
        st.write(
            f"Média nas últimas 5 partidas: {recent['last5']:.1f}; nas últimas 10: {recent['last10']:.1f}."
        )
    allowed = factors.get("opponent_allowed", {}).get(stat)
    if allowed is not None:
        st.write(
            f"O adversário cedeu em média {allowed:.1f} {labels[stat].lower()} por jogo no recorte recente."
        )
    if factors.get("rest_days") is not None:
        st.write(f"Intervalo desde a última partida: {factors['rest_days']:.0f} dia(s).")
    if not factors:
        st.caption("Esta captura antiga tem menos detalhes de contexto preservados.")
    minutes = player.get("minutes_context", {})
    st.caption("Minutos: " + minutes.get("status", "Referência do histórico disponível"))
    st.caption(
        "Escalação e restrição de minutos não confirmadas. Os fatores são contexto, não causas comprovadas."
    )
    with st.expander("Modelo e origem desta estimativa"):
        st.caption(
            f"Modelo: {snapshot['model'].get('id', 'sem identificação')} · "
            f"histórico até {snapshot['history_end']}"
        )
        st.caption(
            f"Fonte: {snapshot.get('source', 'não informada')} · "
            f"{player.get('history_games', '—')} jogos no histórico"
        )
        st.json(
            {
                k: estimate[k]
                for k in ("bayes", "xgboost", "ml_weight", "feedback_correction")
                if k in estimate
            }
        )
