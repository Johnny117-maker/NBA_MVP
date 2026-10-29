"""Histórico diário: previsões originais, comparação e exportação para impressão."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.analysis_archive import read_snapshots, snapshot_html, snapshot_table
from src.injuries import current_pick_players
from src.live_types import EASTERN, utc_now
from src.prop_model import PROP_LABELS
from src.sync_runtime import ensure_auto_sync

from .formatters import format_decimal_br
from .navigation import page_link


@st.fragment(run_every=30)
def archived_preview(path: str | Path, day: str, key: str, eligible_only: bool = False) -> None:
    snapshots = read_snapshots(path, day)
    if not snapshots:
        return
    players = [(snapshot, player) for snapshot in snapshots for player in snapshot["players"]]
    if eligible_only and players:
        pool = pd.DataFrame([{"player_name": player["name"]} for _, player in players])
        eligible = set(current_pick_players(path, pool).index)
        players = [pair for index, pair in enumerate(players) if index in eligible]
    if not players:
        return
    with st.container(border=True):
        st.subheader("O que previmos antes dos jogos")
        players.sort(key=lambda pair: pair[1]["stats"]["pts"]["projected"], reverse=True)
        for column, (snapshot, player) in zip(st.columns(3), players[:3], strict=False):
            with column:
                st.markdown(f"**{player['name']}** · {player['team']}")
                st.metric("Pontos previstos", format_decimal_br(player["stats"]["pts"]["projected"]))
                stamp = pd.Timestamp(snapshot["captured_at"]).tz_convert("America/Sao_Paulo")
                st.caption(f"{snapshot['away']} @ {snapshot['home']} · salvo às {stamp:%H:%M}")
        st.caption(
            "Projeções originais preservadas. Participação dos atletas não confirmada."
            + (" Nesta prévia, lesões e dúvidas do boletim atual foram filtradas." if eligible_only else "")
        )
        with st.container(key=key):
            page_link("archive", "Abrir histórico e comparar resultados")


@st.fragment(run_every=30)
def archive_panel(path: str | Path, day: str) -> None:
    snapshots = read_snapshots(path, day)
    if not snapshots:
        st.info(
            "Ainda não há fotografias pré-jogo para esta data. O monitor salva os destaques quando encontra "
            "um jogo agendado e histórico suficiente, antes do início. Datas passadas não são reconstruídas."
        )
        return
    table = snapshot_table(path, day)
    counts = len({(r["game_key"], r["player_id"]) for r in table.to_dict("records")})
    resolved = table.loc[table["actual"].notna()]
    metrics = st.columns(3)
    metrics[0].metric("Jogos com previsão salva", len(snapshots))
    metrics[1].metric("Destaques registrados", counts)
    metrics[2].metric("Projeções com resultado", len(resolved))
    mode = st.segmented_control(
        "Visualização",
        ["Antes dos jogos", "Previsão × resultado", "Detalhes e impressão"],
        default="Antes dos jogos",
        required=True,
    )
    if mode == "Antes dos jogos":
        st.caption(
            "Cada linha corresponde ao primeiro registro pré-jogo. As faixas P10–P90 são experimentais."
        )
        for snapshot in snapshots:
            with st.container(border=True):
                st.subheader(f"{snapshot['away']} @ {snapshot['home']}")
                stamp = pd.Timestamp(snapshot["captured_at"]).tz_convert("America/Sao_Paulo")
                st.caption(f"Registrado em {stamp:%d/%m/%Y às %H:%M:%S} · horário de Brasília")
                rows = []
                for player in snapshot["players"]:
                    rows.append(
                        {
                            "Jogador": player["name"],
                            "Time": player["team"],
                            **{
                                label: round(player["stats"][stat]["projected"], 1)
                                for stat, label in (
                                    ("pts", "Pontos previstos"),
                                    ("reb", "Rebotes previstos"),
                                    ("ast", "Assistências previstas"),
                                )
                            },
                            "Minutos esperados": round(player["minutes"], 1),
                        }
                    )
                st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Previsões originais dos destaques")
                st.caption("Seleção baseada na forma recente; escalações e participação não confirmadas.")
    elif mode == "Previsão × resultado":
        stat = st.segmented_control(
            "Estatística",
            list(PROP_LABELS),
            format_func=lambda s: PROP_LABELS[s],
            default="pts",
            required=True,
        )
        selected = table.loc[table["stat"].eq(stat)]
        scored = selected.loc[selected["actual"].notna()]
        if not scored.empty:
            st.metric("Erro absoluto médio", format_decimal_br(scored["error"].abs().mean(), 2))
            st.caption(f"{len(scored)} projeções realizadas; atletas sem participação não entram no erro.")
        st.dataframe(
            selected[["matchup", "player", "projected", "low", "high", "actual", "error", "status"]].rename(
                columns={
                    "matchup": "Jogo",
                    "player": "Jogador",
                    "projected": "Previsto",
                    "low": "P10",
                    "high": "P90",
                    "actual": "Real",
                    "error": "Real − previsto",
                    "status": "Situação",
                }
            ),
            hide_index=True,
            alt="Comparação das previsões preservadas com os resultados da partida exata",
        )
        st.download_button(
            "Baixar comparação CSV",
            table.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"previsoes_{day}.csv",
            mime="text/csv",
            icon=":material/download:",
        )
    else:
        for snapshot in snapshots:
            with st.expander(f"{snapshot['away']} @ {snapshot['home']} · fotografia original"):
                st.caption(f"Modelo: {snapshot['model']['id']} · histórico até {snapshot['history_end']}")
                st.caption(f"Fonte do calendário: {snapshot['source']} · integridade SHA-256 verificada")
                st.caption(
                    "O HTML contém apenas a previsão original. Abra o arquivo e use Ctrl+P para imprimir."
                )
                st.download_button(
                    "Baixar fotografia para impressão",
                    snapshot_html(snapshot).encode("utf-8"),
                    file_name=f"previsao_{day}_{snapshot['away']}_{snapshot['home']}.html",
                    mime="text/html",
                    key=snapshot["id"] + "_html",
                    icon=":material/print:",
                )
                st.download_button(
                    "Baixar registro completo JSON",
                    json.dumps(snapshot, ensure_ascii=False, indent=2),
                    file_name=f"previsao_{snapshot['id']}.json",
                    mime="application/json",
                    key=snapshot["id"] + "_json",
                )
                names = [p["name"] for p in snapshot["players"]]
                chosen = st.selectbox("Detalhar jogador", names, key=snapshot["id"] + "_player")
                player = next(p for p in snapshot["players"] if p["name"] == chosen)
                st.dataframe(
                    pd.DataFrame(player["stats"]).T.rename_axis("Estatística").reset_index(),
                    hide_index=True,
                    alt="Estimativas bayesianas, XGBoost, peso da combinação e faixas do jogador",
                )
                st.json(player["context"], expanded=False)


def request_archive_refresh(path: str | Path) -> None:
    st.caption(
        "O monitor registra a primeira previsão de cada jogo do dia NBA (fuso de Nova York). "
        "Os arquivos ficam no computador, mesmo depois de fechar o projeto. "
        "Para registrar novos dias automaticamente, mantenha o servidor em execução."
    )
    if st.button("Verificar registros do dia", icon=":material/sync:"):
        service = ensure_auto_sync(path)
        if service:
            service.request_refresh()
            st.info("Verificação solicitada ao monitor. Os registros aparecerão automaticamente.")
        else:
            st.info("A sincronização automática está desativada na configuração do ambiente.")
    st.caption(f"Hoje no calendário NBA: {utc_now().astimezone(EASTERN):%d/%m/%Y}")
