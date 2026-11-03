from __future__ import annotations

import pandas as pd
import streamlit as st

from src.prop_explanations import compare_line, line_context, projection_components


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
    context = line_context(player, stat, line)
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
        st.caption(
            f"Over: {context['over_min']} ou mais. Under: {context['under_max']} ou menos. "
            + (
                f"Empate: exatamente {context['push']}."
                if context["push"] is not None
                else "Esta linha não permite empate."
            )
        )
        preferred = "Over" if probability["over"] > probability["under"] else "Under"
        st.write(
            f"Nesta linha, o cálculo atribui mais chance ao {preferred}. "
            f"A produção estimada é {estimate['projected']:.1f} {labels[stat].lower()}; "
            "o resultado real pode ficar acima ou abaixo dessa média."
        )
    evidence = snapshot.get("model", {}).get("validation", {}).get("stats", {}).get(stat)
    if evidence:
        st.caption(
            f"Evidência do método no teste histórico: {evidence['status']}. "
            f"Erro médio {evidence['mae']:.2f} em {evidence['n']} observações. "
            "Essa amostra reúne vários atletas; não valida este jogador individualmente."
        )
    else:
        st.caption(
            "Esta captura não preservou um teste independente do método. Probabilidade ainda experimental."
        )
    probability_context = estimate.get("probability_context", {})
    if probability_context:
        st.caption("Distribuição usada: " + probability_context["status"] + ".")
    if line != float(estimate.get("line", line)):
        st.caption(
            "A linha foi alterada para consulta. "
            "Ela pode ter cobertura diferente da grade do teste histórico."
        )
    st.caption("A validação pré-jogo não se aplica às probabilidades condicionais de uma partida ao vivo.")
    st.caption("Referência estatística; a comparação não é cotação de casa nem modifica a captura original.")
    st.markdown("**O que sabemos antes do jogo**")
    factors = player.get("factors", {})
    recent = factors.get("recent", {}).get(stat, {})
    if recent.get("last5") is not None:
        st.write(
            f"Média nas últimas 5 partidas: {recent['last5']:.1f}; nas últimas 10: {recent['last10']:.1f}."
        )
    season = factors.get("season", {})
    season_mean = season.get("means", {}).get(stat)
    if season_mean is not None:
        st.write(
            f"Temporada na base usada: média {season_mean:.1f} em {season['games']} partidas anteriores."
        )
    if context["sample"]:
        st.write(
            f"Nos {context['sample']} jogos anteriores preservados: {context['recent_over']} acima da linha, "
            f"{context['recent_under']} abaixo e {context['recent_push']} empates. "
            "É uma frequência passada, não a probabilidade do próximo jogo."
        )
    if factors.get("recent_games") and st.toggle("Ver os jogos usados no contexto", key=key + "_recent"):
        st.dataframe(
            pd.DataFrame(factors["recent_games"]).rename(
                columns={
                    "day": "Data",
                    "minutes": "Minutos",
                    "pts": "Pontos",
                    "reb": "Rebotes",
                    "ast": "Assistências",
                }
            ),
            hide_index=True,
            alt="Últimas partidas disponíveis antes da captura original",
        )
    allowed = factors.get("opponent_allowed", {}).get(stat)
    if allowed is not None:
        st.write(
            f"O adversário cedeu em média {allowed:.1f} {labels[stat].lower()} por jogo no recorte recente."
        )
        st.caption("Esse total reúne todos os jogadores adversários; não é uma estimativa individual.")
    if factors.get("rest_days") is not None:
        st.write(f"Intervalo desde a última partida: {factors['rest_days']:.0f} dia(s).")
    if not factors:
        st.caption("Esta captura antiga tem menos detalhes de contexto preservados.")
    minutes = player.get("minutes_context", {})
    st.caption("Minutos: " + minutes.get("status", "Referência do histórico disponível"))
    st.caption(
        "Escalação e restrição de minutos não confirmadas. Os fatores são contexto, não causas comprovadas."
    )
    parts = projection_components(estimate)
    if parts:
        with st.expander("Como chegamos ao valor previsto"):
            st.dataframe(
                pd.DataFrame(parts),
                hide_index=True,
                alt="Parcelas aritméticas do Bayes, XGBoost e ajuste que somam a projeção",
            )
            st.caption(
                f"Soma das parcelas: {sum(part['Parcela'] for part in parts):.2f}. "
                "Os valores já incluem o ajuste de minutos usado na captura."
            )
            if float(estimate.get("ml_weight", 0)) == 0:
                st.write("O peso efetivo do XGBoost foi zero nesta previsão; a combinação utiliza Bayes.")
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
