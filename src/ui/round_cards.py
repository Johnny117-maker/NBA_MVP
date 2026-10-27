"""Cartões de atletas e contexto usados na rodada e na tela de palpites."""

from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from src.daily_games import format_tipoff

from .insights import team_identity


def highlight_card(player: pd.Series) -> None:
    code, color = team_identity(str(player.get("team_code", player["team"])))
    name = str(player["player_name"])
    initials = "".join(word[0] for word in name.split()[:2])
    sample = int(player.get("recent_games", 5))
    points = list(player.get("recent_points", []))
    spark = ""
    if points:
        max_points = max(1.0, max(points))
        bars = "".join(
            f'<i style="height:{max(3, value / max_points * 32):.1f}px" title="{value:g} pontos"></i>'
            for value in points
        )
        spark = f'<div class="player-spark" aria-label="Pontuação nos jogos recentes">{bars}</div>'
    delta = float(player["pts_delta"])
    delta_class = "positive" if delta >= 0 else "negative"
    tipoff = format_tipoff(player.get("game_datetime_utc"))
    query = urlencode({"view": "profile", "player_id": str(player["player_id"])})
    st.markdown(
        f'<article class="round-player" style="--team-color:{color}">'
        f'<div class="round-player-top"><span class="round-team">{escape(code)}</span>'
        f"<span>{escape(str(player.get('matchup', '')))}</span></div>"
        f'<div class="player-card-heading"><span class="player-avatar">{escape(initials)}</span>'
        f"<div><h3>{escape(name)}</h3><p>{escape(str(player['tag']))}</p></div></div>"
        '<div class="round-player-stats">'
        f"<div><span>PTS</span><strong>{player['pts_recent']:.1f}</strong></div>"
        f"<div><span>REB</span><strong>{player['reb_recent']:.1f}</strong></div>"
        f"<div><span>AST</span><strong>{player['ast_recent']:.1f}</strong></div></div>"
        f'<div class="round-player-form">{spark}<div class="{delta_class}">{delta:+.1f} PTS'
        "<small>vs. temporada</small></div></div>"
        f'<p class="round-player-meta">{escape(tipoff)}<br>'
        f'Média em {sample} jogos · {player["minutes_recent"]:.1f} min/jogo<br>'
        f"Último jogo: {pd.Timestamp(player['last_game_date']):%d/%m/%Y}</p>"
        f'<a class="profile-link" href="/Jogadores?{escape(query, quote=True)}" target="_self">'
        'Ver perfil e histórico <span aria-hidden="true">→</span></a></article>',
        unsafe_allow_html=True,
    )


def highlights_grid(players: pd.DataFrame) -> None:
    for start in range(0, len(players), 3):
        for column, (_, player) in zip(
            st.columns(3), players.iloc[start : start + 3].iterrows(), strict=False
        ):
            with column:
                highlight_card(player)


def history_notice(form: pd.DataFrame, selected_day: date) -> None:
    if form.empty:
        return
    last = pd.to_datetime(form["last_game_date"], errors="coerce").max()
    if pd.isna(last):
        return
    age = (selected_day - last.date()).days
    if age > 14:
        st.warning(
            f"Histórico de jogadores até {last:%d/%m/%Y} ({age} dias antes da rodada). "
            "Referências históricas: rotação, equipe atual e participação não confirmadas."
        )
    else:
        st.caption(
            f"Última partida no histórico de jogadores: {last:%d/%m/%Y}. "
            "Participação e escalação não confirmadas."
        )


def matchup_strip(game: pd.Series) -> None:
    st.markdown(
        f'<div class="matchup-strip"><strong>{escape(str(game["away_team_tricode"]))}'
        f" <span>@</span> {escape(str(game['home_team_tricode']))}</strong>"
        f"<span>{escape(format_tipoff(game.get('game_datetime_utc')))}</span></div>",
        unsafe_allow_html=True,
    )
