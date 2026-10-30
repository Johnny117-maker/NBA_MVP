from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.analysis_archive import read_snapshots
from src.injuries import injury_snapshot
from src.live_types import LiveGame
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
from src.player_matchups import read_matchups
from src.team_defense import REGULAR, defense_fingerprint, defense_tables
from src.ui.data_quality import data_quality_panel
from src.ui.defense import render_team_charts
from src.ui.live import _live_games
from src.ui.navigation import page_link
from src.ui.pick_detail import pick_detail
from src.ui.saved_picks import saved_picks_panel


@st.cache_data(ttl=120, max_entries=12, show_spinner=False)
def _defense(path, season, fingerprint):
    return defense_tables(path, season, REGULAR, 10)


@st.cache_data(ttl=120, max_entries=12, show_spinner=False)
def _assignments(path, season, fingerprint):
    return read_matchups(path, season, REGULAR)


def match_center(path: str | Path, game: LiveGame, mode: str) -> None:
    st.subheader(
        f"{TEAM_ABBREVIATION_TO_NAME.get(game.away, game.away)} × "
        f"{TEAM_ABBREVIATION_TO_NAME.get(game.home, game.home)}"
    )
    if game.kickoff:
        stamp = pd.Timestamp(game.kickoff).tz_convert("America/Sao_Paulo")
        st.caption(f"{stamp:%d/%m às %H:%M} · Brasília · fonte {game.source}")
    data_quality_panel(path)
    if mode == "Resumo":
        _live_games([game])
        records = [s for s in read_snapshots(path, game.day) if s["game_key"] == game.key]
        st.caption(f"{len(records)} captura pré-jogo preservada para este confronto.")
        if records and records[0].get("team_pick"):
            pick = records[0]["team_pick"]
            st.metric(
                "Favorito na captura pré-jogo",
                pick["favorite"],
                help="Estimativa preservada antes da partida",
            )
            st.caption(f"Chance estimada naquela captura: {pick['probability']:.1%}")
    elif mode == "Palpites":
        if game.state == "pre":
            schedule = pd.DataFrame([dict(home_team_tricode=game.home, away_team_tricode=game.away)])
            if not saved_picks_panel(path, game.day, schedule):
                st.info("Sem captura disponível com jogadores elegíveis para este confronto.")
        else:
            records = [s for s in read_snapshots(path, game.day) if s["game_key"] == game.key]
            if records:
                st.caption("Previsão original anterior ao jogo; não é uma nova recomendação de participação.")
                player = st.selectbox(
                    "Ver registro do jogador", records[0]["players"], format_func=lambda p: p["name"]
                )
                pick_detail(records[0], player, key="center_original")
            else:
                st.info("Não há previsão original para este jogo. Não serão criadas capturas retroativas.")
        page_link("archive", "Abrir histórico e resultados")
    elif mode == "Disponibilidade":
        rows, state = injury_snapshot(path)
        rows = rows.loc[rows.team.isin([game.home, game.away])]
        st.caption(
            f"Fonte {state.get('source', 'indisponível')} · "
            f"referência {state.get('source_as_of', 'desconhecida')}"
        )
        if rows.empty:
            st.info("Sem registros destas equipes no boletim disponível. Isso não confirma a escalação.")
        else:
            st.dataframe(
                rows[["player", "team", "status", "injury", "note"]].rename(
                    columns={
                        "player": "Jogador",
                        "team": "Time",
                        "status": "Situação",
                        "injury": "Lesão",
                        "note": "Informação",
                    }
                ),
                hide_index=True,
                alt="Disponibilidade dos atletas das duas equipes",
            )
    elif mode == "Defesa":
        if not game.regular_season:
            st.info("A fase deste confronto não está classificada no recorte defensivo da temporada regular.")
            return
        fingerprint = defense_fingerprint(path)
        summary, zones = _defense(str(path), game.season, fingerprint)
        if summary.empty:
            st.info("Histórico defensivo ainda indisponível nesta temporada.")
        else:
            selected = summary.loc[summary.team.isin([game.home, game.away])].copy()
            selected["opp_3p_pct"] = selected["opp_3p_pct"] * 100
            st.dataframe(
                selected[["team_name", "games", "drtg", "opp_3pa", "opp_3p_pct", "paint_allowed_100"]].rename(
                    columns={
                        "team_name": "Equipe",
                        "games": "Jogos",
                        "drtg": "Pontos cedidos / 100 posses",
                        "opp_3pa": "Tentativas de 3 cedidas",
                        "opp_3p_pct": "Conversão de 3 cedida (%)",
                        "paint_allowed_100": "Pontos no garrafão / 100 posses",
                    }
                ),
                hide_index=True,
                alt="Comparação defensiva das equipes nos últimos dez jogos disponíveis",
            )
            if st.toggle("Mostrar mapa defensivo", key="center_defense_map"):
                team = st.selectbox("Defesa da equipe", [game.away, game.home], key="center_defense_team")
                render_team_charts(str(path), game.season, REGULAR, team, 10, zones)
        assignments = _assignments(str(path), game.season, fingerprint)
        if not assignments.empty:
            assignments = assignments.loc[
                assignments.game_date.astype(str).str[:10].eq(game.day)
                & assignments.off_team.isin([game.home, game.away])
                & assignments.def_team.isin([game.home, game.away])
                & assignments.off_team.ne(assignments.def_team)
            ]
        st.markdown("**Marcações publicadas desta partida**")
        if assignments.empty:
            st.caption(
                "Ainda não há registros publicados. Não se presume um marcador por posição ou escalação."
            )
        else:
            st.dataframe(
                assignments[["off_name", "def_name", "seconds", "possessions", "points"]].rename(
                    columns={
                        "off_name": "Atacante",
                        "def_name": "Defensor",
                        "seconds": "Segundos atribuídos",
                        "possessions": "Posses parciais",
                        "points": "Pontos atribuídos",
                    }
                ),
                hide_index=True,
                alt="Confrontos individuais publicados da partida selecionada",
            )
            st.caption("Agregados publicados por confronto; não identificam cada posse em tempo real.")
    else:
        _live_games([game])
        page_link("opportunities", "Analisar linhas com as observações ao vivo")
