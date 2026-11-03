from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src.analysis_archive import archive_path
from src.forecast_performance import (
    calibration_bins,
    paired_comparison,
    performance_rows,
    probability_metrics,
    quantity_metrics,
)
from src.live_types import EASTERN, utc_now
from src.ui.navigation import page_link


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def _load(path: str, version: int, start: str, end: str):
    return performance_rows(path, start, end)


def performance_panel(path: str | Path) -> None:
    from src.ui.validation import validation_panel

    evidence = st.segmented_control(
        "Origem da evidência",
        ["Capturas pré-jogo", "Teste histórico independente"],
        default="Capturas pré-jogo",
        required=True,
    )
    if evidence == "Teste histórico independente":
        validation_panel(path)
        return
    st.subheader("O que previmos e o que aconteceu")
    today = utc_now().astimezone(EASTERN).date()
    period = st.segmented_control(
        "Período", ["7 dias", "30 dias", "90 dias"], default="30 dias", required=True
    )
    days = int(str(period).split()[0])
    archive = archive_path(path)
    table = _load(
        str(path),
        archive.stat().st_mtime_ns if archive.exists() else 0,
        (today - timedelta(days=days - 1)).isoformat(),
        today.isoformat(),
    )
    if table.empty:
        st.info("Ainda não há capturas pré-jogo neste período. O painel será preenchido automaticamente.")
        page_link("archive", "Consultar o histórico diário")
        return
    labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}
    stat = st.segmented_control(
        "Estatística", list(labels), format_func=lambda value: labels[value], default="pts", required=True
    )
    selected = table.loc[table.stat.eq(stat)]
    model = st.selectbox("Versão da previsão", ["Todas", *sorted(selected.model.unique())])
    if model != "Todas":
        selected = selected.loc[selected.model.eq(model)]
    player = st.selectbox("Jogador", ["Todos", *sorted(selected.player.unique())], key="performance_player")
    if player != "Todos":
        selected = selected.loc[selected.player.eq(player)]
    metrics, probability = quantity_metrics(selected), probability_metrics(selected)
    columns = st.columns(3)
    columns[0].metric("Resultados comparados", metrics["n"])
    columns[1].metric("Erro médio", f"{metrics['mae']:.2f}" if metrics["mae"] is not None else "—")
    columns[2].metric(
        "Aguardando resultado",
        int(selected.status.isin(["Aguardando resultado", "Aguardando conferência final"]).sum()),
    )
    st.caption(
        "O erro médio é a diferença absoluta entre previsto e realizado. Ausências ficam fora da conta. "
        "Amostras pequenas ainda não comprovam desempenho estável."
    )
    if "pre_game_valid" in selected and not selected.pre_game_valid.all():
        st.warning("Capturas sem proveniência pré-jogo verificável foram excluídas das métricas.")
    mode = st.segmented_control(
        "Analisar",
        ["Resultados", "Probabilidades", "Minutos", "Comparar modelos"],
        default="Resultados",
        required=True,
    )
    resolved = selected.dropna(subset=["actual", "projected"])
    if mode == "Resultados":
        if not resolved.empty:
            daily = resolved.assign(Erro=resolved.error.abs()).groupby("day", as_index=False).Erro.mean()
            daily = daily.rename(columns={"day": "Dia", "Erro": "Erro médio"})
            st.line_chart(
                daily, x="Dia", y="Erro médio", alt="Evolução diária do erro das previsões originais"
            )
            st.caption(f"Viés médio: {metrics['bias']:+.2f}. Positivo indica superestimação.")
            if metrics["coverage"] is not None:
                st.caption(
                    f"Resultado dentro da faixa P10–P90: {metrics['coverage']:.1%} da amostra com intervalo."
                )
        st.dataframe(
            selected[["day", "player", "team", "projected", "actual", "error", "status"]].rename(
                columns={
                    "day": "Dia",
                    "player": "Jogador",
                    "team": "Time",
                    "projected": "Previsto",
                    "actual": "Realizado",
                    "error": "Previsto − realizado",
                    "status": "Situação",
                }
            ),
            hide_index=True,
            alt="Previsões salvas e resultados reais da partida exata",
        )
    elif mode == "Probabilidades":
        side = st.segmented_control("Lado avaliado", ["Over", "Under"], default="Over", required=True).lower()
        probability = probability_metrics(selected, side=side)
        st.caption(
            "Avaliação da chance de superar a linha estatística original de meia unidade; sem odds de casas."
        )
        if not probability["n"]:
            st.info("Aguardando resultados com linha e probabilidade válidas para avaliar.")
            return
        columns = st.columns(2)
        columns[0].metric("Brier score", f"{probability['brier']:.3f}")
        columns[1].metric("Log loss", f"{probability['log_loss']:.3f}")
        st.caption("Menor é melhor nestas duas métricas; elas também refletem fatores além da calibração.")
        bins = calibration_bins(selected, side=side)
        chart = (
            alt.Chart(bins)
            .mark_circle(size=90)
            .encode(
                x=alt.X("predicted:Q", title="Chance prevista", scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("observed:Q", title="Frequência observada", scale=alt.Scale(domain=[0, 1])),
                tooltip=["n:Q", "predicted:Q", "observed:Q"],
            )
        )
        intervals = alt.Chart(bins).mark_rule().encode(x="predicted:Q", y="low:Q", y2="high:Q")
        diagonal = (
            alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]}))
            .mark_line(strokeDash=[4, 4])
            .encode(x="x:Q", y="y:Q")
        )
        st.altair_chart(
            diagonal + intervals + chart, alt="Calibração com frequência real e intervalo de Wilson de 95%"
        )
        st.caption(
            "A diagonal representa concordância. As barras mostram a incerteza da frequência observada."
        )
        st.caption(
            "Over e Under são complementares nas linhas de meia unidade; a amostra não é contada duas vezes."
        )
        st.dataframe(
            bins.rename(
                columns={
                    "n": "Resultados",
                    "predicted": "Chance média",
                    "observed": "Frequência real",
                    "low": "Limite inferior",
                    "high": "Limite superior",
                }
            ).drop(columns="bucket"),
            hide_index=True,
            alt="Amostra por faixa de probabilidade",
        )
    elif mode == "Minutos":
        sample = selected.dropna(subset=["minutes", "actual_minutes"])
        if sample.empty:
            st.info(
                "Aguardando resultados com minutos registrados. Capturas antigas podem não ter esse campo."
            )
        else:
            st.metric("Erro médio de minutos", f"{(sample.minutes - sample.actual_minutes).abs().mean():.2f}")
            st.dataframe(
                sample[["day", "player", "minutes", "actual_minutes"]].rename(
                    columns={
                        "day": "Dia",
                        "player": "Jogador",
                        "minutes": "Minutos previstos",
                        "actual_minutes": "Minutos reais",
                    }
                ),
                hide_index=True,
                alt="Comparação de minutos previstos e registrados para quem participou",
            )
        st.caption("A previsão é condicionada à participação. Ausências e minutos não informados ficam fora.")
    else:
        comparison = paired_comparison(selected)
        if comparison.empty:
            st.info("Aguardando capturas com estimativas Bayes e XGBoost na mesma amostra resolvida.")
        else:
            st.dataframe(
                comparison, hide_index=True, alt="Comparação dos modelos nos mesmos jogadores e jogos"
            )
            st.caption(
                "Comparação pareada de previsões anteriores às partidas. "
                "Não recria palpites para datas passadas."
            )
