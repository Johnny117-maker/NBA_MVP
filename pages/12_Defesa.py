from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import pyarrow.parquet as pq
import streamlit as st

from src.history_store import connect_history, history_root, read_assets
from src.store import DEFAULT_DB_PATH, list_seasons
from src.team_defense import (
    REGULAR,
    collect_team_tracking,
    defense_fingerprint,
    defense_tables,
    rim_defenders,
)
from src.ui import components, theme

st.set_page_config(
    page_title="Defesa dos times — NBA Analytics Lab", page_icon=":material/shield:", layout="wide"
)
theme.inject_base_style("defense")
components.page_header(
    "Onde cada defesa cede espaço.",
    "Compare perímetro, garrafão e eficiência com a fonte e a amostra de cada indicador.",
    category="DEFESA DOS TIMES",
)


@st.cache_data(ttl=120, max_entries=16, show_spinner=False)
def load_defense(path: str, season: str, phase: str, last_n: int, fingerprint: tuple):
    return defense_tables(Path(path), season, phase, last_n)


def value(number, percent=False):
    return "—" if pd.isna(number) else (f"{number:.1%}" if percent else f"{number:.1f}")


with connect_history(DEFAULT_DB_PATH) as connection:
    stored = [row[0] for row in connection.execute("SELECT DISTINCT season FROM team_boxes")]
seasons = sorted(set(stored + list_seasons(DEFAULT_DB_PATH)), reverse=True)
seasons = [season for season in seasons if season >= "2021-22"]
if not seasons:
    st.info("Colete o histórico em Dados e atualizações para analisar a defesa dos times.")
    st.stop()

controls = st.columns([1, 1.4, 1.4])
season = controls[0].selectbox("Temporada", seasons, key="defense_season")
with connect_history(DEFAULT_DB_PATH) as connection:
    phases = [
        row[0]
        for row in connection.execute("SELECT DISTINCT phase FROM team_boxes WHERE season=?", (season,))
    ]
phase_options = [
    item
    for item in (REGULAR, "Playoffs", "Play-in", "Pós-temporada", "Pré-temporada", "Final da NBA Cup")
    if item in phases or item == REGULAR
]
if st.session_state.get("defense_phase") not in phase_options:
    st.session_state.pop("defense_phase",None)
phase = controls[1].selectbox("Fase", phase_options, key="defense_phase")
window = controls[2].selectbox(
    "Amostra", ["Fase inteira", "Últimos 10 jogos", "Últimos 20 jogos"], key="defense_window"
)
last_n = {"Fase inteira": 0, "Últimos 10 jogos": 10, "Últimos 20 jogos": 20}[window]
view = st.segmented_control(
    "Visualização", ["Panorama", "Por time", "Fontes e cobertura"], default="Panorama"
)

assets = read_assets(DEFAULT_DB_PATH)
if view == "Fontes e cobertura":
    st.subheader("Acervo disponível neste computador")
    st.caption(
        "Cada linha do catálogo representa um arquivo público. O mesmo jogo aparece em diferentes "
        "conjuntos; a soma de linhas não representa jogos únicos."
    )
    if assets.empty:
        st.info(
            "O acervo ampliado ainda não foi coletado. Use Dados e atualizações → Base ampliada desde 2022."
        )
    else:
        catalog = assets.groupby("tag", as_index=False).agg(
            arquivos=("name", "size"),
            linhas=("rows", "sum"),
            primeiro_ano=("year", "min"),
            ultimo_ano=("year", "max"),
        )
        st.dataframe(
            catalog.rename(
                columns={
                    "tag": "Conjunto",
                    "arquivos": "Arquivos",
                    "linhas": "Registros",
                    "primeiro_ano": "Primeiro ano final",
                    "ultimo_ano": "Último ano final",
                }
            ),
            hide_index=True,
            alt="Cobertura dos conjuntos de dados NBA e ESPN por categoria e temporada.",
        )
        st.download_button(
            "Exportar catálogo de fontes",
            assets.drop(columns="relative_path").to_csv(index=False).encode("utf-8-sig"),
            "fontes_nba.csv",
            "text/csv",
        )
        selected = st.selectbox(
            "Inspecionar um arquivo",
            assets.index.tolist(),
            format_func=lambda index: f"{assets.loc[index, 'tag']} · {assets.loc[index, 'name']}",
        )
        asset = assets.loc[selected]
        st.caption(
            f"{int(asset['rows']):,} linhas · {int(asset['columns'])} colunas · "
            f"fonte atualizada em {str(asset['source_updated'])[:10]}"
        )
        st.link_button("Abrir arquivo público original", asset["source_url"])
        if st.button("Pré-visualizar 100 registros"):
            parquet = pq.ParquetFile(history_root(DEFAULT_DB_PATH) / asset["relative_path"])
            batch = next(parquet.iter_batches(batch_size=100), None)
            if batch is not None:
                st.dataframe(
                    batch.to_pandas(), hide_index=True, alt="Primeiros cem registros do conjunto selecionado."
                )
    st.info(
        "O histórico preserva pré-temporada, temporada regular, play-in e playoffs. "
        "Os modelos existentes continuam usando a base regular; o acervo bruto fica separado. "
        "Escalações inferidas pelo arquivo não equivalem a stints validados para RAPM."
    )
    st.stop()

with st.spinner("Conferindo a amostra defensiva…"):
    summary, zones = load_defense(
        str(DEFAULT_DB_PATH), season, phase, last_n, defense_fingerprint(DEFAULT_DB_PATH)
    )
if summary.empty:
    st.info("Ainda não há boxscores completos para este recorte. Amplie a base em Dados e atualizações.")
    st.stop()
components.metric_row(
    [
        {"label": "Times com dados", "value": str(len(summary))},
        {"label": "Jogos por time", "value": f"{int(summary.games.min())}–{int(summary.games.max())}"},
        {"label": "Dados até", "value": pd.Timestamp(summary.latest_game.max()).strftime("%d/%m/%Y")},
        {"label": "Arquivos no acervo", "value": str(len(assets))},
    ]
)
if summary.games.min() < 10:
    st.warning(
        "Amostra ainda pequena: os rankings são provisórios e podem mudar bastante nas próximas partidas."
    )

st.caption(
    "Indicadores descritivos, incluindo todos os minutos. Menor é melhor para DRtg, PITP, "
    "3PA e aproveitamento cedidos. DRtg oficial é usado quando cobre a mesma fase e "
    "quantidade de jogos; janelas recentes usam posses estimadas."
)

if view == "Panorama":
    labels = {
        "DRtg": "drtg",
        "Pontos no garrafão cedidos/jogo": "paint_allowed",
        "3PA cedidas/jogo": "opp_3pa",
        "3P% cedido": "opp_3p_pct",
        "FG% cedido a <6 pés (localização)": "rim_fg_pct",
    }
    ranking = st.selectbox("Ordenar a defesa por", list(labels))
    metric = labels[ranking]
    ranked = summary.sort_values(metric, na_position="last").copy()
    chart = ranked.loc[ranked[metric].notna(), ["team_name", metric, "games"]].head(10)
    if not chart.empty:
        st.altair_chart(
            alt.Chart(chart)
            .mark_bar(color="#F97316")
            .encode(
                x=alt.X(
                    metric + ":Q",
                    title=ranking,
                    axis=alt.Axis(format=".0%") if metric.endswith("pct") else alt.Undefined,
                ),
                y=alt.Y("team_name:N", sort="x", title=None),
                tooltip=[
                    alt.Tooltip("team_name:N", title="Time"),
                    alt.Tooltip(
                        metric + ":Q", title=ranking, format=".1%" if metric.endswith("pct") else ".1f"
                    ),
                    alt.Tooltip("games:Q", title="Jogos"),
                ],
            )
            .properties(height=330),
            width="stretch",
            alt="Dez equipes com menores valores no indicador defensivo escolhido.",
        )
    display = ranked[
        [
            "team_name",
            "games",
            "drtg",
            "paint_allowed",
            "opp_3pa",
            "opp_3p_pct",
            "rim_fg_pct",
            "zone_games",
            "drtg_method",
        ]
    ].copy()
    for column in ("opp_3p_pct", "rim_fg_pct"):
        display[column] *= 100
    st.dataframe(
        display,
        hide_index=True,
        height=570,
        column_config={
            "team_name": "Time",
            "games": "Jogos",
            "drtg": st.column_config.NumberColumn("DRtg", format="%.1f"),
            "paint_allowed": st.column_config.NumberColumn("PITP cedidos/jogo", format="%.1f"),
            "opp_3pa": st.column_config.NumberColumn("3PA cedidas/jogo", format="%.1f"),
            "opp_3p_pct": st.column_config.NumberColumn("3P% cedido", format="%.1f%%"),
            "rim_fg_pct": st.column_config.NumberColumn("FG% <6 pés · localização", format="%.1f%%"),
            "zone_games": "Jogos com PBP completo",
            "drtg_method": "Fonte DRtg",
        },
        alt="Ranking defensivo de todas as equipes, com amostra e origem dos indicadores.",
    )
    st.download_button(
        "Exportar análise defensiva",
        ranked.to_csv(index=False).encode("utf-8-sig"),
        f"defesa_{season}.csv",
        "text/csv",
    )
else:
    team = st.selectbox(
        "Time",
        summary.team.tolist(),
        format_func=lambda code: str(summary.loc[summary.team.eq(code), "team_name"].iloc[0]),
    )
    row = summary.loc[summary.team.eq(team)].iloc[0]
    components.metric_row(
        [
            {"label": "DRtg", "value": value(row.drtg)},
            {"label": "PITP cedidos/jogo", "value": value(row.paint_allowed)},
            {"label": "3PA cedidas/jogo", "value": value(row.opp_3pa)},
            {"label": "3P% cedido", "value": value(row.opp_3p_pct, True)},
        ]
    )
    st.caption(
        f"DRtg: {row.drtg_method}. Garrafão: {row.paint_method}, {int(row.paint_games)} jogos. "
        "Perímetro: volume e aproveitamento dos adversários nos boxscores."
    )
    left, right = st.columns(2)
    left.metric(
        "FG% cedido a <6 pés · localização",
        value(row.rim_fg_pct, True),
        help="Acertos/tentativas por coordenadas NBA. Não identifica o defensor mais próximo.",
    )
    right.metric(
        "DFG% <6 pés · tracking oficial",
        value(row.tracking_dfg_pct, True),
        help="Tracking defensivo oficial, quando disponível. Ausência de dados aparece como traço.",
    )
    st.caption(
        f"Regiões: {int(row.zone_games)} de {int(row.games)} jogos com todas as tentativas "
        "adversárias conferidas contra o boxscore. "
        "DFG% de tracking e FG% por localização medem coisas diferentes."
    )
    if row.zone_games:
        selected_zones = zones.loc[zones.team.eq(team)].copy()
        selected_zones["fg_pct"] *= 100
        selected_zones["frequency"] *= 100
        st.subheader("Onde os adversários arremessam")
        st.dataframe(
            selected_zones[["zone", "attempts", "makes", "attempts_game", "fg_pct", "frequency"]],
            hide_index=True,
            column_config={
                "zone": "Região geométrica",
                "attempts": "Tentativas",
                "makes": "Acertos",
                "attempts_game": st.column_config.NumberColumn("Tentativas/jogo", format="%.1f"),
                "fg_pct": st.column_config.NumberColumn("FG% cedido", format="%.1f%%"),
                "frequency": st.column_config.NumberColumn("Frequência", format="%.1f%%"),
            },
            alt="Distribuição dos arremessos adversários por região, com volume e aproveitamento.",
        )
    else:
        st.info("Não há PBP com cobertura integral para detalhar as regiões deste recorte.")
    if phase == REGULAR and not last_n:
        defenders = rim_defenders(DEFAULT_DB_PATH, season, team)
        if not defenders.empty:
            st.subheader("Quem protege o aro")
            st.caption(
                "Tracking individual NBA: tentativas defendidas no aro. "
                "A definição difere do filtro <6 pés; não somamos atletas para criar um DFG% de equipe."
            )
            defenders["rim_pct"] *= 100
            st.dataframe(
                defenders.sort_values("def_rim_fga", ascending=False),
                hide_index=True,
                column_config={
                    "player_name": "Jogador",
                    "gp": "Jogos",
                    "def_rim_fgm": "Acertos cedidos",
                    "def_rim_fga": "Tentativas defendidas no aro",
                    "rim_pct": st.column_config.NumberColumn("DFG% no aro", format="%.1f%%"),
                },
                alt="Defensores da equipe com volume e aproveitamento dos arremessos defendidos no aro.",
            )
    with st.expander("Consultar tracking direto da NBA"):
        st.caption(
            "Consulta gratuita via nba_api. Pode falhar quando stats.nba.com recusa a conexão; "
            "nenhum valor é substituído por zero."
        )
        if phase != REGULAR or last_n:
            st.info("Selecione a temporada regular inteira para consultar este dashboard.")
        elif st.button("Consultar DFG% oficial <6 pés"):
            try:
                collect_team_tracking(DEFAULT_DB_PATH, season, pd.Timestamp(summary.latest_game.max()).date())
                st.rerun()
            except Exception as error:
                st.warning(
                    f"Tracking indisponível nesta conexão ({type(error).__name__}). "
                    "Os dados locais continuam disponíveis."
                )
