"""Cartões e gráficos exploratórios calculados exclusivamente sobre a base exibida."""

from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data import available_teams, team_game_history
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME

TEAM_CODES = {name: code for code, name in TEAM_ABBREVIATION_TO_NAME.items()}
TEAM_COLORS = {
    "BOS": "#34d399",
    "MIL": "#34d399",
    "DAL": "#38bdf8",
    "NYK": "#fb923c",
    "GSW": "#fbbf24",
    "LAL": "#c4a2ff",
    "PHX": "#fb923c",
    "SAC": "#c4a2ff",
    "CHI": "#fb7185",
    "MIA": "#fb7185",
    "CLE": "#fb7185",
    "PHI": "#60a5fa",
    "DEN": "#fbbf24",
    "IND": "#fbbf24",
    "OKC": "#38bdf8",
    "MIN": "#38bdf8",
}


def team_identity(team: str) -> tuple[str, str]:
    code = TEAM_CODES.get(team, team if len(team) <= 4 else "".join(w[0] for w in team.split())[:3])
    return code, TEAM_COLORS.get(code, "#8ba5fa")


def latest_season_games(games: pd.DataFrame) -> pd.DataFrame:
    """Recorte da temporada do jogo mais recente, sem misturar campanhas históricas."""
    if games.empty or "season" not in games:
        return games
    latest = games.sort_values("game_date").iloc[-1]["season"]
    return games[games["season"].eq(latest)]


def team_form_table(games: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    rows = []
    for team in available_teams(games):
        history = team_game_history(games, team)
        recent = history.tail(window)
        rows.append(
            {
                "team": team,
                "wins": int(history["win"].sum()),
                "losses": int(len(history) - history["win"].sum()),
                "recent_wins": int(recent["win"].sum()),
                "sample": len(recent),
                "form": recent["win"].astype(int).tolist(),
                **{
                    key: float(recent[key].mean())
                    for key in ("points_for", "points_against", "off_rating", "def_rating", "net_rating")
                },
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        for key, ascending in (
            ("points_for", False),
            ("points_against", True),
            ("off_rating", False),
            ("def_rating", True),
        ):
            frame[f"rank_{key}"] = frame[key].rank(method="min", ascending=ascending).astype(int)
    return frame


def team_card(row: pd.Series, role: str) -> None:
    code, color = team_identity(str(row["team"]))
    streak = "".join(
        f'<span class="form-result {"is-win" if win else "is-loss"}" '
        f'title="{"Vitória" if win else "Derrota"}">{"V" if win else "D"}</span>'
        for win in row["form"]
    )
    metrics = "".join(
        f"<div><span>{label}</span><strong>{row[key]:.1f}</strong></div>"
        for label, key in (
            ("Pontos feitos", "points_for"),
            ("Pontos sofridos", "points_against"),
            ("Rating ofensivo*", "off_rating"),
            ("Rating defensivo*", "def_rating"),
            ("Saldo de rating*", "net_rating"),
        )
    )
    metrics += (
        f"<div><span>Vitórias recentes</span><strong>"
        f"{int(row['recent_wins'])}/{int(row['sample'])}</strong></div>"
    )
    ranks = "".join(
        f"<div><span>{label}</span><strong>#{int(row[f'rank_{key}'])}</strong></div>"
        for label, key in (
            ("Ataque", "off_rating"),
            ("Defesa", "def_rating"),
            ("Pontos", "points_for"),
            ("Pts sofridos", "points_against"),
        )
    )
    st.markdown(
        f'<article class="team-intel" style="--team-color:{color}">'
        f'<div class="team-intel-head"><span class="team-monogram">{escape(code)}</span>'
        f"<div><h3>{escape(str(row['team']))}</h3><p>{escape(role)}</p></div>"
        f'<div class="team-record"><strong>{int(row["wins"])}–{int(row["losses"])}</strong>'
        "<span>V–D na base</span></div></div>"
        f'<div class="form-strip" aria-label="Sequência de resultados, do mais antigo ao mais recente">'
        f'{streak}</div><div class="intel-grid">{metrics}</div>'
        f'<div class="rank-grid">{ranks}</div></article>',
        unsafe_allow_html=True,
    )


def scoring_frequencies(history: pd.DataFrame, thresholds: list[int]) -> pd.DataFrame:
    """Frequência empírica: acima é > corte; até inclui igualdade. Sem modelo de aposta."""
    points = history["points_for"].dropna()
    if points.empty:
        return pd.DataFrame(columns=thresholds, index=["Acima", "Até"], dtype=float)
    above = [float(points.gt(cut).mean()) for cut in thresholds]
    return pd.DataFrame([above, [1 - value for value in above]], index=["Acima", "Até"], columns=thresholds)


def scoring_map(games: pd.DataFrame, team: str, window: int) -> None:
    history = team_game_history(games, team).tail(window)
    frequency = scoring_frequencies(history, list(range(90, 136, 5)))
    cells = '<div class="frequency-label"></div>' + "".join(
        f'<div class="frequency-label">{cut} pts</div>' for cut in frequency.columns
    )
    for label, values in frequency.iterrows():
        cells += f'<div class="frequency-label">{escape(str(label))}</div>'
        for value in values:
            shade = "high" if value >= 0.6 else "low" if value < 0.4 else "mid"
            cells += f'<div class="frequency-cell frequency-{shade}">{value:.0%}</div>'
    st.markdown(
        f'<div class="frequency-scroll"><div class="frequency-grid">{cells}</div></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Frequência observada em {len(history)} jogos de {team}. "
        "Acima: pontuação maior que o corte; Até: menor ou igual. Não é uma previsão."
    )


def matchup_intel(games: pd.DataFrame, away: str, home: str, key: str) -> None:
    season_games = latest_season_games(games)
    available = available_teams(season_games)
    if away not in available or home not in available:
        st.info("Histórico da temporada mais recente insuficiente para detalhar este confronto.")
        return
    label = str(season_games.iloc[-1]["season"]) if "season" in season_games else "base enviada"
    st.caption(
        f"Temporada {label} · jogos até {season_games['game_date'].max():%d/%m/%Y} · "
        "forma e rankings: últimos 10 jogos de cada equipe · "
        f"comparação entre {len(available)} times da base · sequência da esquerda para a direita."
    )
    form = team_form_table(season_games).set_index("team", drop=False)
    for column, team, role in zip(st.columns(2), (away, home), ("Visitante", "Mandante"), strict=True):
        with column:
            team_card(form.loc[team], role)
    st.caption("*Ratings usam dados oficiais quando coletados; nos demais jogos, aproximação por pontos.")
    with st.container(border=True):
        st.markdown("#### Mapa de pontuação recente")
        controls, sample = st.columns([3, 1])
        with controls:
            selected = st.radio("Equipe do mapa", [away, home], horizontal=True, key=f"{key}_map_team")
        with sample:
            window = st.selectbox("Últimos jogos", [5, 10, 15, 20], index=1, key=f"{key}_map_window")
        scoring_map(season_games, selected, window)
    meetings = (
        season_games[
            ((season_games["home_team"] == home) & (season_games["away_team"] == away))
            | ((season_games["home_team"] == away) & (season_games["away_team"] == home))
        ]
        .sort_values("game_date", ascending=False)
        .head(5)
    )
    with st.expander("Confrontos diretos na temporada", expanded=False):
        if meetings.empty:
            st.caption("Nenhum encontro entre essas equipes na temporada exibida.")
        else:
            display = meetings[["game_date", "away_team", "away_points", "home_points", "home_team"]].copy()
            display["game_date"] = display["game_date"].dt.strftime("%d/%m/%Y")
            display.columns = ["Data", "Visitante", "PTS fora", "PTS casa", "Mandante"]
            st.dataframe(display, hide_index=True, use_container_width=True)


def player_card(name: str, team: str, pts: float, reb: float, ast: float, detail: str = "") -> None:
    code, color = team_identity(team)
    initials = "".join(word[0] for word in name.split()[:2])
    st.markdown(
        f'<article class="player-spotlight" style="--team-color:{color}">'
        f'<div class="player-card-heading"><span class="player-avatar">{escape(initials)}</span>'
        f"<div><h3>{escape(name)}</h3><p>{escape(code)} · {escape(detail)}</p></div></div>"
        f'<div class="player-stat-line"><div><span>PTS</span><strong>{pts:.1f}</strong></div>'
        f"<div><span>REB</span><strong>{reb:.1f}</strong></div>"
        f"<div><span>AST</span><strong>{ast:.1f}</strong></div></div></article>",
        unsafe_allow_html=True,
    )


def performance_bars(history: pd.DataFrame, stat: str, label: str, line: float) -> go.Figure:
    recent = history.sort_values("game_date").tail(20).copy()
    # Eixo categórico mantém partidas na mesma data separadas e espaçamento uniforme.
    x = [str(i) for i in range(len(recent))]
    ticks = [
        f"{day:%d/%m}<br>{escape(str(opp))}"
        for day, opp in zip(recent["game_date"], recent["opponent"], strict=True)
    ]
    figure = go.Figure(
        go.Bar(
            x=x,
            y=recent[stat],
            marker_color=["#22c55e" if v > line else "#ef4444" for v in recent[stat]],
            text=recent[stat],
            textposition="inside",
            textfont={"color": "#ffffff"},
            customdata=ticks,
            hovertemplate="%{customdata}<br>%{y}<extra></extra>",
        )
    )
    figure.add_hline(
        y=line,
        line_color="#fbbf24",
        line_width=1.5,
        annotation_text=f"Referência {line:g}",
        annotation_position="top left",
    )
    figure.update_layout(
        height=370,
        margin=dict(l=10, r=15, t=30, b=15),
        showlegend=False,
        yaxis_title=label,
        xaxis=dict(tickmode="array", tickvals=x, ticktext=ticks),
        bargap=0.22,
    )
    return figure


def ranking_list(frame: pd.DataFrame, title: str) -> None:
    """Ranking de forma, sem confundir a ordenação com classificação oficial."""
    st.markdown(f"#### {title}")
    for position, (_, row) in enumerate(frame.head(5).iterrows(), 1):
        code, color = team_identity(str(row["team"]))
        st.markdown(
            f'<div class="ranking-row"><b class="rank-position">{position:02d}</b>'
            f"<div><strong>{escape(str(row['team']))}</strong>"
            f"<span>{int(row['wins'])} V · {int(row['losses'])} D na base</span></div>"
            f'<b class="team-tag" style="color:{color}">{escape(code)}</b></div>',
            unsafe_allow_html=True,
        )
