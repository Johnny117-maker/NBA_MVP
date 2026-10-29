from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from src.history_store import connect_history
from src.player_defense_fit import analyze_player_fit
from src.player_matchups import collect_game_matchups, defender_summary, read_matchups
from src.store import DEFAULT_DB_PATH, list_seasons
from src.team_defense import defense_fingerprint
from src.ui import components, theme

st.set_page_config(
    page_title="Marcações e encaixes — NBA Analytics Lab", page_icon=":material/person_search:", layout="wide"
)
theme.inject_base_style("matchups")
components.page_header(
    "Quem marcou. Como o jogador respondeu.",
    "Marcações registradas por partida e produção contra perfis defensivos pré-jogo.",
    category="MARCAÇÕES E ENCAIXES",
)
st.caption(
    "A NBA atribui tempo, posses parciais e arremessos a diferentes defensores. "
    "Os registros são agregados por confronto, sem uma sequência de marcadores segundo a segundo."
)


@st.cache_data(ttl=120, max_entries=20, show_spinner=False)
def load_player(path, season, phase, player_id, fingerprint):
    rows = read_matchups(path, season, phase, off_id=player_id)
    fit, games = analyze_player_fit(path, player_id, season, phase)
    return rows, defender_summary(rows), fit, games


def show_assignments(rows):
    if rows.empty:
        st.info(
            "Ainda não há marcações publicadas/importadas para este recorte. "
            "Escalação e posição em quadra não identificam, por si só, quem marcou cada atleta."
        )
        return
    display = rows.copy()
    display["minutes"] = display.seconds / 60
    display["fg_pct"] = 100 * display.fgm / display.fga.replace(0, float("nan"))
    st.dataframe(
        display[
            [
                "game_date",
                "off_name",
                "def_name",
                "def_position",
                "minutes",
                "possessions",
                "points",
                "fgm",
                "fga",
                "fg_pct",
                "fg3m",
                "fg3a",
                "switches",
            ]
        ],
        hide_index=True,
        column_config={
            "game_date": "Data",
            "off_name": "Atacante",
            "def_name": "Defensor",
            "def_position": "Posição declarada",
            "minutes": st.column_config.NumberColumn("Tempo atribuído (min)", format="%.2f"),
            "possessions": st.column_config.NumberColumn("Posses parciais", format="%.1f"),
            "points": "PTS atribuídos",
            "fgm": "FGM",
            "fga": "FGA",
            "fg_pct": st.column_config.NumberColumn("FG%", format="%.1f%%"),
            "fg3m": "3PM",
            "fg3a": "3PA",
            "switches": "Trocas registradas",
        },
        alt="Confrontos entre atacantes e defensores registrados pela NBA, com exposição e aproveitamento.",
    )
    st.download_button(
        "Exportar marcações deste recorte",
        rows.to_csv(index=False).encode("utf-8-sig"),
        "marcacoes_nba.csv",
        "text/csv",
    )


with connect_history(DEFAULT_DB_PATH) as connection:
    available = [
        row[0]
        for row in connection.execute("SELECT DISTINCT season FROM player_matchups ORDER BY season DESC")
    ]
    box_seasons = [row[0] for row in connection.execute("SELECT DISTINCT season FROM team_boxes")]
options = sorted(set(available + box_seasons + list_seasons(DEFAULT_DB_PATH)), reverse=True)
options = [season for season in options if season >= "2021-22"]
if not options:
    st.info("Amplie a base em Dados e atualizações para acessar matchups e perfis defensivos.")
    st.stop()
cols = st.columns([1, 1, 1.2])
season = cols[0].selectbox(
    "Temporada", options, index=options.index(available[0]) if available else 0, key="matchups_season"
)
with connect_history(DEFAULT_DB_PATH) as connection:
    known_phases = {
        row[0]
        for row in connection.execute(
            "SELECT phase FROM team_boxes WHERE season=? "
            "UNION SELECT phase FROM player_matchups WHERE season=?",
            (season, season),
        )
    }
phase_options = [
    item
    for item in (
        "Temporada regular",
        "Playoffs",
        "Play-in",
        "Pré-temporada",
        "Final da NBA Cup",
        "Pós-temporada",
    )
    if item in known_phases
]
phase_options = phase_options or ["Temporada regular"]
if st.session_state.get("matchups_phase") not in phase_options:
    st.session_state.pop("matchups_phase", None)
phase = cols[1].selectbox("Fase", phase_options, key="matchups_phase")
mode = cols[2].selectbox("Analisar", ["Jogador", "Marcador", "Partida"], key="matchups_mode")
with connect_history(DEFAULT_DB_PATH) as connection:
    coverage = connection.execute(
        "SELECT COUNT(DISTINCT game_id),MAX(game_date) FROM player_matchups WHERE season=? AND phase=?",
        (season, phase),
    ).fetchone()
    expected = connection.execute(
        "SELECT COUNT(DISTINCT game_id) FROM team_boxes WHERE season=? AND phase=?", (season, phase)
    ).fetchone()[0]
st.caption(
    f"Cobertura de marcações: {coverage[0]} de {expected or '—'} jogos no acervo. "
    f"Último registro: {coverage[1] or 'ainda indisponível'}."
)

if mode == "Marcador":
    from src.ui.defenders import render_defender

    render_defender(DEFAULT_DB_PATH, season, phase)
    st.stop()

if mode == "Partida":
    with connect_history(DEFAULT_DB_PATH) as connection:
        games = pd.read_sql_query(
            "SELECT game_id,game_date,team,opponent FROM team_boxes "
            "WHERE season=? AND phase=? AND is_home=1 ORDER BY game_date DESC,game_id DESC",
            connection,
            params=(season, phase),
        )
    if games.empty:
        st.info("Não há partidas encerradas neste recorte do acervo.")
        st.stop()
    index = st.selectbox(
        "Partida encerrada",
        games.index.tolist(),
        format_func=lambda i: (
            f"{games.loc[i, 'game_date']} · {games.loc[i, 'opponent']} @ {games.loc[i, 'team']}"
        ),
    )
    game = games.loc[index]
    rows = read_matchups(DEFAULT_DB_PATH, season, phase, game_id=game.game_id)
    if not rows.empty:
        primary = rows.sort_values("seconds", ascending=False).drop_duplicates("off_id")
        st.subheader("Maior tempo de marcação atribuído por atacante")
        st.dataframe(
            primary[["off_name", "def_name", "seconds", "possessions"]].rename(
                columns={
                    "off_name": "Atacante",
                    "def_name": "Defensor com maior tempo",
                    "seconds": "Segundos atribuídos",
                    "possessions": "Posses parciais",
                }
            ),
            hide_index=True,
            alt="Defensor com maior tempo atribuído a cada atacante; não representa marcação exclusiva.",
        )
        athlete = st.selectbox("Filtrar atacante", ["Todos"] + sorted(rows.off_name.unique().tolist()))
        if athlete != "Todos":
            rows = rows.loc[rows.off_name.eq(athlete)]
    show_assignments(rows)
    if st.button("Consultar marcações oficiais desta partida"):
        try:
            count = collect_game_matchups(DEFAULT_DB_PATH, str(game.game_id))
            if count:
                st.rerun()
            else:
                st.info("A NBA ainda não retornou marcações para esta partida.")
        except Exception as error:
            st.warning(
                f"Consulta indisponível ({type(error).__name__}). Os registros salvos foram preservados."
            )
    st.stop()

with connect_history(DEFAULT_DB_PATH) as connection:
    players = pd.read_sql_query(
        "SELECT off_id player_id,MAX(off_name) player_name FROM player_matchups "
        "WHERE season=? AND phase=? GROUP BY off_id ORDER BY player_name",
        connection,
        params=(season, phase),
    )
if players.empty:
    with sqlite3.connect(DEFAULT_DB_PATH) as connection:
        players = pd.read_sql_query(
            "SELECT player_id,MAX(player_name) player_name FROM player_game_stats "
            "WHERE season=? GROUP BY player_id ORDER BY player_name",
            connection,
            params=(season,),
        )
if players.empty:
    st.info("Ainda não há jogadores identificados neste recorte.")
    st.stop()
requested = st.session_state.pop("matchups_player_id", None)
default = (
    players.index[players.player_id.eq(requested)].tolist()
    if requested is not None
    else players.index[players.player_name.eq("Jalen Brunson")].tolist()
)
key = f"matchups_player_{season}_{phase}"
if requested is not None and default:
    st.session_state[key] = default[0]
chosen = st.selectbox(
    "Jogador",
    players.index.tolist(),
    index=default[0] if default else 0,
    format_func=lambda i: str(players.loc[i, "player_name"]),
    key=key,
)
player = players.loc[chosen]
with st.spinner("Conferindo marcações e contexto pré-jogo…"):
    rows, defenders, fit, logs = load_player(
        str(DEFAULT_DB_PATH), season, phase, int(player.player_id), defense_fingerprint(DEFAULT_DB_PATH)
    )
view = st.segmented_control(
    "Detalhamento",
    ["Defensores enfrentados", "Por partida", "Encaixe defensivo"],
    default="Defensores enfrentados",
)

if view == "Defensores enfrentados":
    if defenders.empty:
        show_assignments(rows)
        st.stop()
    components.metric_row(
        [
            {"label": "Jogos com tracking", "value": str(rows.game_id.nunique())},
            {"label": "Defensores encontrados", "value": str(len(defenders))},
            {"label": "Posses parciais", "value": f"{rows.possessions.sum():.1f}"},
            {"label": "FGA atribuídas", "value": str(int(rows.fga.sum()))},
        ]
    )
    minimum = st.slider(
        "Tentativas mínimas contra o defensor",
        0,
        max(1, int(defenders.fga.max())),
        min(10, int(defenders.fga.max())),
    )
    display = defenders.loc[defenders.fga.ge(minimum)].copy()
    display["fg_pct"] *= 100
    st.dataframe(
        display[
            [
                "def_name",
                "def_position",
                "games",
                "minutes",
                "possessions",
                "points",
                "fga",
                "fg_pct",
                "pts_100_partial",
            ]
        ],
        hide_index=True,
        column_config={
            "def_name": "Defensor",
            "def_position": "Posição no elenco",
            "games": "Jogos",
            "minutes": st.column_config.NumberColumn("Minutos atribuídos", format="%.1f"),
            "possessions": st.column_config.NumberColumn("Posses parciais", format="%.1f"),
            "points": "PTS atribuídos",
            "fga": "FGA",
            "fg_pct": st.column_config.NumberColumn("FG% contra o defensor", format="%.1f%%"),
            "pts_100_partial": st.column_config.NumberColumn("PTS/100 posses parciais", format="%.1f"),
        },
        alt="Histórico contra defensores específicos, ponderado pelo volume de arremessos.",
    )
    positional = rows.groupby("def_position", as_index=False).agg(
        games=("game_id", "nunique"),
        possessions=("possessions", "sum"),
        points=("points", "sum"),
        fgm=("fgm", "sum"),
        fga=("fga", "sum"),
    )
    positional["fg_pct"] = 100 * positional.fgm / positional.fga.replace(0, float("nan"))
    st.subheader("Contra tipos de jogadores")
    st.caption(
        "Posição declarada no elenco da temporada: G, F, C ou híbrida. "
        "A posição não define sozinha a habilidade do marcador."
    )
    st.dataframe(
        positional.rename(
            columns={
                "def_position": "Posição do defensor",
                "games": "Jogos",
                "possessions": "Posses parciais",
                "points": "PTS atribuídos",
                "fgm": "FGM",
                "fga": "FGA",
                "fg_pct": "FG%",
            }
        ),
        hide_index=True,
        alt="Produção contra defensores agrupados pela posição declarada.",
    )
elif view == "Por partida":
    dates = rows[["game_id", "game_date", "def_team"]].drop_duplicates() if not rows.empty else pd.DataFrame()
    if dates.empty:
        show_assignments(rows)
    else:
        choice = st.selectbox(
            "Partida do jogador",
            dates.index.tolist(),
            format_func=lambda i: f"{dates.loc[i, 'game_date']} · vs {dates.loc[i, 'def_team']}",
        )
        show_assignments(rows.loc[rows.game_id.eq(dates.loc[choice, "game_id"])])
else:
    st.subheader(f"{player.player_name} contra perfis defensivos")
    st.caption(
        "Perfis por terços da liga: últimos 10 jogos antes da partida, com 5 jogos prévios no mínimo. "
        "Os esquemas zona, drop ou blitz não são inferidos destes números."
    )
    with st.expander("Como os perfis são definidos"):
        st.write(
            "Garrafão: pontos no garrafão cedidos por 100 posses estimadas. "
            "Perímetro: percentis de 3PA cedidas por 100 posses e 3P% cedido. "
            "Eficiência geral: DRtg estimado. "
            "As referências de todas as equipes usam datas anteriores ao jogo."
        )
    if fit.empty:
        st.info("Ainda não há histórico pré-jogo suficiente para esta análise.")
        st.stop()
    dimension = st.selectbox("Dimensão defensiva", fit.dimension.unique().tolist())
    observed = fit.loc[fit.dimension.eq(dimension)].copy()
    st.dataframe(
        observed[
            [
                "profile",
                "games",
                "pts_game",
                "minutes_game",
                "pts36",
                "comparison_pts36",
                "difference_pts36",
                "difference_low",
                "difference_high",
                "interpretation",
            ]
        ],
        hide_index=True,
        column_config={
            "profile": "Concessão do adversário",
            "games": "Jogos",
            "pts_game": st.column_config.NumberColumn("PTS/jogo", format="%.1f"),
            "minutes_game": st.column_config.NumberColumn("MIN/jogo", format="%.1f"),
            "pts36": st.column_config.NumberColumn("PTS/36", format="%.1f"),
            "comparison_pts36": st.column_config.NumberColumn("PTS/36 nos outros perfis", format="%.1f"),
            "difference_pts36": st.column_config.NumberColumn("Diferença por 36", format="%+.1f"),
            "difference_low": st.column_config.NumberColumn("IC95% diferença: inferior", format="%+.1f"),
            "difference_high": st.column_config.NumberColumn("IC95% diferença: superior", format="%+.1f"),
            "interpretation": "Leitura da amostra",
        },
        alt="Produção por perfil defensivo pré-jogo, com amostra, ajuste por minutos e incerteza.",
    )
    strong = observed.loc[observed.interpretation.eq("Produção maior observada")]
    if not strong.empty:
        best = strong.sort_values("difference_pts36", ascending=False).iloc[0]
        st.info(
            f"Nesta amostra, {player.player_name} produziu {best.pts36:.1f} PTS/36 contra o perfil "
            f"'{best.profile}', em {int(best.games)} jogos. A associação não garante o próximo confronto."
        )
    else:
        st.info(
            "A amostra não sustenta uma vantagem clara contra um perfil nesta dimensão. "
            "Diferenças pequenas ou intervalos amplos continuam aparecendo como incertos."
        )
    st.caption(
        "Comparação com os demais perfis do mesmo jogador/temporada/fase. IC95% por bootstrap de jogos; "
        "exige 10 partidas e 200 minutos em cada grupo. Associação exploratória, sem ajuste completo "
        "para escalação, lesões e força do calendário."
    )
    st.download_button(
        "Exportar análise de encaixe",
        fit.to_csv(index=False).encode("utf-8-sig"),
        "encaixe_defensivo.csv",
        "text/csv",
    )
