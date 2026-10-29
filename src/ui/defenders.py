from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.history_store import connect_history
from src.player_matchups import defender_opponents
from src.team_defense import defense_fingerprint
from src.ui import components


@st.cache_data(ttl=120, max_entries=20, show_spinner=False)
def load_defender(path, season, phase, defender_id, fingerprint):
    return defender_opponents(path, season, phase, defender_id)


def render_defender(path, season, phase):
    with connect_history(path) as connection:
        players = pd.read_sql_query(
            "SELECT def_id,MAX(def_name) def_name,def_team,SUM(fga) fga FROM player_matchups "
            "WHERE season=? AND phase=? GROUP BY def_id,def_team ORDER BY fga DESC",
            connection,
            params=(season, phase),
        )
    if players.empty:
        st.info("Não há marcações publicadas neste recorte para analisar os defensores.")
        return
    team = st.selectbox("Equipe do marcador", ["Todas"] + sorted(players.def_team.unique().tolist()))
    if team != "Todas":
        players = players.loc[players.def_team.eq(team)]
    chosen = st.selectbox(
        "Marcador",
        players.index.tolist(),
        format_func=lambda i: f"{players.loc[i, 'def_name']} · {players.loc[i, 'def_team']}",
    )
    player = players.loc[chosen]
    rows, summary = load_defender(str(path), season, phase, int(player.def_id), defense_fingerprint(path))
    st.subheader(f"O que os atacantes produziram contra {player.def_name}")
    st.caption(
        "Confrontos atribuídos pelo tracking da NBA. "
        "Trocas e ajuda defensiva limitam a interpretação individual."
    )
    attempts = rows.fga.sum()
    fg = rows.fgm.sum() / attempts if attempts else float("nan")
    paired = summary.loc[summary.difference_pp.notna()]
    difference = (
        100
        * (paired.fgm.sum() / paired.fga.sum() - (paired.fga * paired.reference_pct).sum() / paired.fga.sum())
        if not paired.empty
        else float("nan")
    )
    components.metric_row(
        [
            {"label": "Jogos com tracking", "value": str(rows.game_id.nunique())},
            {"label": "Arremessos defendidos", "value": str(int(attempts))},
            {"label": "FG% cedido", "value": f"{fg:.1%}" if pd.notna(fg) else "—"},
            {
                "label": "Diferença na amostra pareada",
                "value": f"{difference:+.1f} p.p." if pd.notna(difference) else "—",
            },
        ]
    )
    st.caption(
        "Diferença: FG% contra este marcador menos FG% dos mesmos atacantes contra os outros marcadores, "
        "A ponderação usa as tentativas neste confronto. "
        "Exige 5 FGA por par e 20 FGA de referência por atacante. "
        "Valores menores indicam menor conversão observada. "
        "A comparação não mede efeito causal nem um DRtg individual."
    )
    minimum = (
        st.slider(
            "FGA mínimas por atacante",
            1,
            max(1, int(summary.fga.max())),
            min(5, int(summary.fga.max())),
            key="defender_min_fga",
        )
        if summary.fga.max() > 1
        else 1
    )
    selected = summary.loc[summary.fga.ge(minimum)].copy()
    comparison = selected.head(15).melt(
        id_vars=["off_name", "fga"],
        value_vars=["fg_pct", "reference_pct"],
        var_name="Amostra",
        value_name="FG%",
    )
    comparison["Amostra"] = comparison.Amostra.map(
        {"fg_pct": "Contra este marcador", "reference_pct": "Outros marcadores"}
    )
    st.altair_chart(
        alt.Chart(comparison.dropna())
        .mark_bar()
        .encode(
            x=alt.X("FG%:Q", axis=alt.Axis(format=".0%")),
            y=alt.Y("off_name:N", title="Atacante"),
            yOffset="Amostra:N",
            color=alt.Color("Amostra:N", scale=alt.Scale(range=["#f97316", "#64748b"])),
            tooltip=["off_name:N", "Amostra:N", alt.Tooltip("FG%:Q", format=".1%"), "fga:Q"],
        )
        .properties(height=max(220, min(650, len(selected.head(15)) * 38))),
        alt="Conversão dos atacantes contra o marcador escolhido e os demais na mesma temporada e fase.",
    )
    display = selected.copy()
    for col in ("fg_pct", "fg3_pct", "efg_pct", "reference_pct"):
        display[col] *= 100
    st.dataframe(
        display[
            [
                "off_name",
                "off_team",
                "games",
                "possessions",
                "points",
                "fga",
                "fg_pct",
                "fg3_pct",
                "efg_pct",
                "reference_pct",
                "difference_pp",
                "pts_100_partial",
            ]
        ],
        hide_index=True,
        column_config={
            "off_name": "Atacante",
            "off_team": "Time",
            "games": "Jogos",
            "possessions": "Posses parciais",
            "points": "PTS atribuídos",
            "fga": "FGA",
            "fg_pct": st.column_config.NumberColumn("FG% cedido", format="%.1f%%"),
            "fg3_pct": st.column_config.NumberColumn("3P% cedido", format="%.1f%%"),
            "efg_pct": st.column_config.NumberColumn("eFG% cedido", format="%.1f%%"),
            "reference_pct": st.column_config.NumberColumn("FG% contra os outros", format="%.1f%%"),
            "difference_pp": st.column_config.NumberColumn("Diferença (p.p.)", format="%+.1f"),
            "pts_100_partial": st.column_config.NumberColumn("PTS/100 posses parciais", format="%.1f"),
        },
        alt="Produção de cada atacante sob a marcação do defensor escolhido e volume de exposição.",
    )
    st.download_button(
        "Exportar análise do marcador",
        summary.to_csv(index=False).encode("utf-8-sig"),
        "analise_marcador.csv",
        "text/csv",
    )
    with st.expander("Registros por partida"):
        st.dataframe(
            rows[["game_date", "off_name", "off_team", "seconds", "possessions", "points", "fgm", "fga"]],
            hide_index=True,
            alt="Registros de confrontos por partida com tempo e arremessos atribuídos.",
        )
