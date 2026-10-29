from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.defense_analytics import (
    DEFENSE_LABELS,
    DEFENSE_WEIGHTS,
    court_cells,
    defense_evolution,
    defense_index,
    defense_shots,
)
from src.defense_charts import defense_court_chart
from src.team_defense import defense_fingerprint


@st.cache_data(ttl=300, max_entries=16, show_spinner=False)
def load_court(path, season, phase, team, last_n, fingerprint):
    return defense_shots(path, season, phase, team, last_n)


@st.cache_data(ttl=300, max_entries=24, show_spinner=False)
def load_evolution(path, season, phase, team, fingerprint):
    return defense_evolution(path, season, phase, team)


def render_defense_index(summary):
    st.subheader("Parâmetro defensivo · 0 a 100")
    st.caption(
        "Índice descritivo relativo às equipes elegíveis neste recorte. Maior indica melhores percentis "
        "nos critérios escolhidos. Não é uma probabilidade nem uma métrica oficial NBA."
    )
    with st.expander("Ajustar critérios e pesos", expanded=True):
        cols = st.columns(4)
        weights = {
            key: col.number_input(
                DEFENSE_LABELS[key],
                min_value=0.0,
                max_value=100.0,
                value=value,
                step=5.0,
                key="defense_weight_" + key,
            )
            for col, (key, value) in zip(cols, DEFENSE_WEIGHTS.items(), strict=True)
        }
        minimum = st.slider("Jogos mínimos por equipe", 1, 30, 5, key="defense_score_min_games")
        st.caption(
            "Os pesos positivos são normalizados para 100%. Equipes com critério ausente não recebem nota. "
            "O critério de garrafão exige PITP em todos os jogos do recorte. Empates usam percentil médio."
        )
    if not sum(weights.values()):
        st.info("Defina ao menos um peso maior que zero.")
        return
    indexed = defense_index(summary, weights, minimum)
    ranked = indexed.loc[indexed.defense_index.notna()].sort_values("defense_index", ascending=False)
    if minimum < 5:
        st.warning("Índice provisório: menos de cinco jogos por equipe é uma amostra muito pequena.")
    if ranked.empty:
        st.info("Ainda não há duas equipes com os critérios completos e a amostra mínima escolhida.")
    else:
        st.altair_chart(
            alt.Chart(ranked)
            .mark_bar(color="#f97316")
            .encode(
                x=alt.X("defense_index:Q", title="Índice defensivo", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("team_name:N", title=None, sort="-x"),
                tooltip=["team_name:N", "games:Q", alt.Tooltip("defense_index:Q", format=".1f")],
            )
            .properties(height=max(250, len(ranked) * 23)),
            alt="Índice defensivo relativo da liga com pesos configuráveis.",
        )
        st.dataframe(
            ranked[["team_name", "games", "defense_index"]].rename(
                columns={"team_name": "Equipe", "games": "Jogos", "defense_index": "Índice defensivo"}
            ),
            hide_index=True,
            alt="Nota defensiva e amostra das equipes elegíveis.",
        )
    st.subheader("Garrafão e perímetro")
    scatter = summary.dropna(subset=["paint_allowed_100", "opp_3p_pct"])
    st.altair_chart(
        alt.Chart(scatter)
        .mark_circle(opacity=0.8)
        .encode(
            x=alt.X("paint_allowed_100:Q", title="PITP cedidos por 100 posses", scale=alt.Scale(zero=False)),
            y=alt.Y(
                "opp_3p_pct:Q", title="3P% cedido", axis=alt.Axis(format=".0%"), scale=alt.Scale(zero=False)
            ),
            size=alt.Size("games:Q", title="Jogos"),
            color=alt.Color("drtg:Q", title="DRtg", scale=alt.Scale(scheme="orangered")),
            tooltip=[
                "team_name:N",
                "games:Q",
                alt.Tooltip("paint_allowed_100:Q", format=".1f"),
                alt.Tooltip("opp_3p_pct:Q", format=".1%"),
                alt.Tooltip("drtg:Q", format=".1f"),
            ],
        )
        .properties(height=400),
        alt="Comparação das concessões de garrafão e perímetro; menores valores ficam à esquerda e abaixo.",
    )
    st.download_button(
        "Exportar índice e critérios",
        indexed.to_csv(index=False).encode("utf-8-sig"),
        "indice_defensivo.csv",
        "text/csv",
    )


def render_team_charts(path, season, phase, team, last_n, zones):
    st.subheader("Mapa defensivo da equipe")
    st.caption(
        "Localização dos arremessos adversários. "
        "O mapa não descreve a posição dos marcadores ou esquemas táticos. "
        "Só entram jogos com todas as FGA adversárias conferidas contra o boxscore."
    )
    metric = st.segmented_control(
        "Colorir o mapa por", ["FG% cedido", "Volume de tentativas"], default="FG% cedido"
    )
    minimum = st.slider("Tentativas mínimas por célula", 1, 30, 5, key="defense_map_min")
    with st.spinner("Carregando os arremessos cedidos…"):
        shots = load_court(str(path), season, phase, team, last_n, defense_fingerprint(path))
    if shots.empty:
        st.info("Não há coordenadas com cobertura integral para o mapa deste recorte.")
    else:
        cells = court_cells(shots)
        st.plotly_chart(
            defense_court_chart(
                cells, metric="fg_pct" if metric == "FG% cedido" else "attempts", minimum=minimum
            ),
            width="stretch",
            alt="Mapa dos arremessos cedidos com volume e conversão por célula de três pés.",
        )
        st.caption(
            f"{len(shots):,} tentativas em {shots.game_id.nunique()} jogos completos. "
            "Células de 3 pés; vermelho indica maior FG% cedido. Células abaixo do mínimo ficam ocultas."
        )
        st.download_button(
            "Exportar células do mapa",
            cells.to_csv(index=False).encode("utf-8-sig"),
            "mapa_defesa.csv",
            "text/csv",
        )
    selected = zones.loc[zones.team.eq(team)]
    if not selected.empty and selected.attempts.sum() > 0:
        baseline = zones.groupby("zone", as_index=False)[["attempts", "makes"]].sum()
        baseline["fg_pct"] = baseline.makes / baseline.attempts.replace(0, float("nan"))
        comparison = pd.concat([selected.assign(Referência="Equipe"), baseline.assign(Referência="Liga")])
        st.subheader("Aproveitamento cedido por região")
        st.altair_chart(
            alt.Chart(comparison)
            .mark_bar()
            .encode(
                x=alt.X("fg_pct:Q", title="FG% cedido", axis=alt.Axis(format=".0%")),
                y=alt.Y("zone:N", title="Região"),
                yOffset="Referência:N",
                color="Referência:N",
                tooltip=["zone:N", "Referência:N", "attempts:Q", alt.Tooltip("fg_pct:Q", format=".1%")],
            )
            .properties(height=320),
            alt="Conversão cedida por região da equipe e média ponderada da liga no mesmo recorte.",
        )
    evolution = load_evolution(str(path), season, phase, team, defense_fingerprint(path))
    if not evolution.empty and evolution.drtg_10.notna().any():
        st.subheader("Evolução da defesa")
        st.caption(
            "DRtg estimado pela soma de pontos e posses dos últimos 10 jogos, com mínimo de 5. "
            "A série percorre toda a fase escolhida."
        )
        st.altair_chart(
            alt.Chart(evolution)
            .mark_line(color="#f97316", point=True)
            .encode(
                x=alt.X("game_date:T", title="Data"),
                y=alt.Y("drtg_10:Q", title="DRtg estimado · 10 jogos", scale=alt.Scale(zero=False)),
                tooltip=["game_date:T", "opponent:N", alt.Tooltip("drtg_10:Q", format=".1f")],
            ),
            alt="Evolução do DRtg estimado da equipe em janelas móveis de até dez jogos.",
        )
