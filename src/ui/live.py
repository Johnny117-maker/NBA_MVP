"""Painel de oportunidades com atualização independente dos modelos históricos."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.analysis_archive import apply_frozen_pregame_props
from src.injuries import filter_candidate_rows
from src.live_providers import ApiKeys, FeedClient, ProviderError
from src.live_store import get_state, read_live_games, set_state
from src.live_types import EASTERN, LiveGame, current_season, utc_now
from src.optional_feeds import fetch_market_quotes
from src.prop_model import (
    PROP_LABELS,
    conditional_prop,
    load_prop_history,
    opportunity_candidates,
    player_prior,
    players_for_game,
)
from src.provider_settings import load_api_keys
from src.sync_runtime import ensure_auto_sync

from .formatters import format_datetime_br
from .navigation import page_link


@st.cache_data(ttl=60, max_entries=1, show_spinner=False)
def _history(path: str, version: int) -> pd.DataFrame:
    _ = version
    return load_prop_history(path)


@st.cache_data(ttl=300, max_entries=2, show_spinner=False)
def _pregame_candidates(history: pd.DataFrame, contexts: tuple, _now: datetime) -> list[dict]:
    # O horário e o estado atuais são verificados ANTES do cache. O histórico
    # e o contexto completo da previsão entram na chave; ticks de rede não entram.
    games = [
        LiveGame(
            external_id, source, day, season, home, away, "pre", "", kickoff=kickoff, regular_season=regular
        )
        for external_id, source, day, season, home, away, kickoff, regular in contexts
    ]
    return opportunity_candidates(history, games, _now)


def current_candidates(history: pd.DataFrame, games: list[LiveGame], now: datetime) -> list[dict]:
    contexts = []
    for game in games:
        if game.state != "pre" or not game.kickoff:
            continue
        kickoff = pd.to_datetime(game.kickoff, utc=True, errors="coerce")
        if pd.isna(kickoff) or kickoff.to_pydatetime() <= now:
            continue
        contexts.append(
            (
                game.external_id,
                game.source,
                game.day,
                game.season,
                game.home,
                game.away,
                game.kickoff,
                game.regular_season,
            )
        )
    rows = _pregame_candidates(history, tuple(contexts), now) if contexts else []
    # Ao vivo: relógio, estatísticas e validade da fonte são recalculados em cada tick.
    rows.extend(opportunity_candidates(history, [g for g in games if g.state == "live"], now))
    return sorted(rows, key=lambda row: (row["state"] == "live", row["probability"]), reverse=True)


def current_games(path: str | Path) -> list[LiveGame]:
    from datetime import timedelta

    day = utc_now().astimezone(EASTERN).date()
    games = read_live_games(path, day.isoformat())
    games.extend(
        game
        for game in read_live_games(path, (day - timedelta(days=1)).isoformat())
        if game.state == "live" and game.fresh(utc_now())
    )
    return games


def sync_status(path: str | Path, *, detailed: bool = False) -> dict:
    status = get_state(path, "status", {})
    if not status:
        st.info("Aguardando a primeira sincronização da temporada atual. A coleta ocorre em segundo plano.")
        return status
    archive_day = status.get("archive_latest_game")
    source = status.get("live_source")
    successful_at = pd.to_datetime(status.get("live_success_at"), utc=True, errors="coerce")
    recent = (
        successful_at is not None
        and not pd.isna(successful_at)
        and (pd.Timestamp(utc_now()) - successful_at).total_seconds() <= 300
    )
    if status.get("live_available") and recent:
        local_stamp = successful_at.tz_convert("America/Sao_Paulo")
        st.caption(f"Fonte consultada: {source} · {format_datetime_br(local_stamp)} (Brasília)")
    else:
        st.caption(
            "Consulta ao vivo indisponível nesta rede. Arquivos públicos não são exibidos como tempo real."
        )
    if archive_day:
        st.caption(
            f"Temporada {status.get('season')} · arquivo público com partidas até "
            f"{pd.Timestamp(archive_day).strftime('%d/%m/%Y')}. Atualização do arquivo: até uma vez por hora."
        )
    if detailed:
        for error in status.get("errors", []):
            st.warning(error)
        if status.get("rejected_games"):
            st.warning(
                f"{len(status['rejected_games'])} boxscores aguardam validação antes de entrar no histórico."
            )
            with st.expander("Detalhes da validação"):
                for reason in status["rejected_games"]:
                    st.caption(reason)
    return status


def _prop_card(row: dict) -> None:
    with st.container(border=True, height="stretch"):
        st.caption(f"{row['matchup']} · {'Durante o jogo' if row['state'] == 'live' else 'Pré-jogo'}")
        st.subheader(row["player_name"])
        st.metric(
            f"{row['side']} {row['line']:.1f} · {PROP_LABELS[row['stat']]}",
            f"{row['probability']:.0%}",
            help="Estimativa experimental, ainda sem calibração ao vivo.",
        )
        st.caption(f"Projeção: {row['projected']:.1f} · faixa estimada: {row['low']:.0f}–{row['high']:.0f}")
        if row["state"] == "live":
            st.caption(
                f"Já registrado: {row['observed']} · {row['remaining_minutes']:.1f} minutos futuros estimados"
            )
        st.caption(f"Últimos jogos: {row['recent_mean']:.1f} · temporada: {row['season_mean']:.1f}")
        st.caption(f"{row['season_games']} jogos na temporada · {row['confidence']} · {row['line_source']}")
    if row.get("snapshot_id"):
        st.caption("Projeção preservada no Histórico diário · Bayes com comparação XGBoost")


def _live_games(games: list[LiveGame]) -> None:
    if not games:
        st.info("Nenhuma partida disponível para a data atual. Consulte o status das fontes.")
    for game in games:
        with st.container(border=True):
            score = (
                f"{game.away_score if game.away_score is not None else '—'} × "
                f"{game.home_score if game.home_score is not None else '—'}"
            )
            st.subheader(f"{game.away} @ {game.home} · {score}")
            fresh = game.state == "live" and game.fresh(utc_now()) and game.elapsed is not None
            if fresh:
                clock = float(game.clock_minutes or 0)
                clock_min, clock_sec = divmod(int(round(clock * 60)), 60)
                st.caption(
                    f"Em andamento · período {game.period} · {clock_min:02d}:{clock_sec:02d} no relógio"
                )
            else:
                label = {"pre": "Agendado", "final": "Encerrado", "live": "Aguardando estatísticas recentes"}
                st.caption(label.get(game.state, "Estado indisponível"))
            st.caption(
                f"Fonte: {game.source} · "
                f"{'arquivo periódico; sem acompanhamento ao vivo' if game.archive else 'consulta direta'}"
            )
            if game.players:
                table = [
                    {
                        "Jogador": p.name,
                        "Equipe": p.team,
                        "MIN": p.minutes,
                        "PTS": p.stats.get("pts"),
                        "REB": p.stats.get("reb"),
                        "AST": p.stats.get("ast"),
                    }
                    for p in game.players
                    if p.minutes is not None and p.minutes > 0
                ]
                st.dataframe(
                    pd.DataFrame(table),
                    hide_index=True,
                    alt=f"Estatísticas individuais de {game.away} contra {game.home}",
                )
            elif game.state == "live":
                st.info("O placar está disponível, mas falta um boxscore recente para analisar os jogadores.")


def _manual_line(path: str | Path, history: pd.DataFrame, games: list[LiveGame]) -> None:
    eligible = [game for game in games if game.state in {"pre", "live"}]
    if not eligible:
        st.info("Aguardando um confronto agendado ou em andamento para analisar uma linha.")
        return
    index = st.selectbox(
        "Confronto",
        range(len(eligible)),
        format_func=lambda i: f"{eligible[i].away} @ {eligible[i].home}",
        key="prop_game",
    )
    game = eligible[index]
    players = players_for_game(history, game)
    if not players:
        st.info("Ainda não há jogadores com contexto para este confronto.")
        return
    selected = st.selectbox(
        "Jogador", range(len(players)), format_func=lambda i: players[i].name, key=f"prop_player_{game.key}"
    )
    player = players[selected]
    stat = st.segmented_control(
        "Estatística",
        list(PROP_LABELS),
        default="pts",
        required=True,
        format_func=lambda key: PROP_LABELS[key],
        key="prop_stat",
    )
    prior = player_prior(history, int(player.canonical_id or 0), game, str(stat))
    if prior is None:
        st.info("Histórico insuficiente ou sem partidas recentes na temporada atual para este jogador.")
        return
    suggested = float(int(prior["reference_mean"]) + 0.5)
    line = st.number_input(
        "Linha para comparar",
        min_value=0.0,
        max_value=200.0,
        value=suggested,
        step=0.5,
        key=f"prop_line_{game.key}_{player.canonical_id}_{stat}",
    )
    row = conditional_prop(history, player, game, str(stat), line)
    if row is None:
        st.warning("A análise está pausada: faltam minutos, relógio ou estatísticas recentes da partida.")
    else:
        columns = st.columns(3)
        for column, title, key in zip(
            columns, ("Over", "Under", "Devolução / empate na linha"), ("over", "under", "push"), strict=True
        ):
            column.metric(title, f"{row[key]:.1%}")
        st.caption(
            f"Já registrado: {row['observed']} · projeção final {row['projected']:.1f} · "
            f"minutos restantes do atleta estimados: {row['remaining_minutes']:.1f}."
        )
        if not row["eligible"]:
            st.info("Linha já decidida ou contexto de participação reduzida; não entra nas oportunidades.")
    keys = _keys_for_ui()
    if st.button("Consultar linhas das casas", disabled=not bool(keys.odds), key="prop_fetch_odds"):
        try:
            quotes = fetch_market_quotes(FeedClient(path, keys), game)
            set_state(path, "quotes:" + game.key, quotes)
        except ProviderError as error:
            st.warning(str(error))
    quotes = get_state(path, "quotes:" + game.key, [])
    if quotes:
        st.dataframe(
            pd.DataFrame(quotes).drop(columns="name_key", errors="ignore"),
            hide_index=True,
            alt="Linhas e cotações consultadas na The Odds API, com horário de atualização",
        )
    if not keys.odds:
        st.caption(
            "The Odds API é opcional. Sem chave, informe manualmente uma linha "
            "ou use a referência estatística."
        )


def _source_settings(path: str | Path) -> None:
    sync_status(path, detailed=True)
    keys = _keys_for_ui()
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Fonte": "NBA / ESPN",
                    "Chave": "Dispensada",
                    "Uso": "Placar e boxscore diretos, se acessíveis",
                },
                {
                    "Fonte": "SportsDataverse / ESPN",
                    "Chave": "Dispensada",
                    "Uso": "Temporada atual; arquivo periódico",
                },
                {
                    "Fonte": "API-Sports / RapidAPI",
                    "Chave": "Configurada" if keys.api_sports or keys.rapidapi else "Opcional",
                    "Uso": "Até 95 chamadas/dia neste projeto; cache de 15 minutos",
                },
                {
                    "Fonte": "balldontlie",
                    "Chave": "Configurada" if keys.balldontlie else "Opcional",
                    "Uso": f"Plano {keys.bdl_plan}; grátis sem boxscores de jogadores",
                },
                {
                    "Fonte": "The Odds API",
                    "Chave": "Configurada" if keys.odds else "Opcional",
                    "Uso": "Consulta por botão; limite local 12 créditos/dia e 450/mês",
                },
            ]
        ),
        hide_index=True,
        alt="Fontes de dados, disponibilidade das chaves e limites locais",
    )
    st.caption(
        "Copie .streamlit/secrets.example.toml para .streamlit/secrets.toml, preencha localmente "
        "e reinicie o projeto. Não publique nem envie suas chaves."
    )
    st.caption(
        "O monitor funciona enquanto o servidor estiver aberto, mesmo sem manter esta aba em primeiro plano. "
        "As fontes públicas diretas são consultadas de 30 segundos a 5 minutos, conforme a rodada; "
        "falhas aguardam 5 minutos antes de nova tentativa."
    )


def _keys_for_ui() -> ApiKeys:
    try:
        return load_api_keys()
    except ValueError as error:
        st.warning(str(error))
        return ApiKeys()


@st.fragment(run_every=30)
def opportunities_panel(path: str | Path, compact: bool = False) -> None:
    st.subheader("Oportunidades da rodada")
    st.caption(f"Temporada {current_season()} · PTS, REB e AST · atualização automática")
    status = sync_status(path)
    prefix = "home_props" if compact else "all_props"
    if not compact:
        if st.button("Verificar atualizações", key=prefix + "_refresh"):
            service = ensure_auto_sync(path)
            if service is not None:
                service.request_refresh()
                st.info("Verificação solicitada. O painel acompanha o resultado automaticamente.")
        mode = st.segmented_control(
            "Explorar",
            ["Oportunidades", "Jogos ao vivo", "Analisar linha", "Fontes"],
            default="Oportunidades",
            required=True,
            key=prefix + "_mode",
        )
    else:
        mode = "Oportunidades"
    games = current_games(path)
    if mode == "Fontes":
        _source_settings(path)
        return
    if mode == "Jogos ao vivo":
        _live_games(games)
        return
    version = Path(path).stat().st_mtime_ns if Path(path).exists() else 0
    history = _history(str(path), version)
    if mode == "Analisar linha":
        _manual_line(path, history, games)
        return
    st.caption(
        "Linhas de referência da temporada, com apoio do histórico anterior em amostras curtas. "
        "Mínimo de 3 jogos atuais para a seleção automática; sem cotação de casa. "
        "Estimativas experimentais; participação pré-jogo não confirmada."
    )
    threshold = 0.6
    stats = list(PROP_LABELS)
    side = "Ambos"
    if not compact:
        markets_column, side_column, threshold_column = st.columns([2, 1.2, 1.5], vertical_alignment="bottom")
        with markets_column:
            stats = st.multiselect(
                "Mercados",
                list(PROP_LABELS),
                default=list(PROP_LABELS),
                format_func=lambda key: PROP_LABELS[key],
                key=prefix + "_stats",
            )
        with side_column:
            side = st.segmented_control(
                "Lado", ["Ambos", "Over", "Under"], default="Ambos", required=True, key=prefix + "_side"
            )
        with threshold_column:
            threshold = st.slider(
                "Probabilidade mínima", 0.5, 0.95, 0.6, 0.01, format="%.2f", key=prefix + "_threshold"
            )
    candidates = apply_frozen_pregame_props(
        path, current_candidates(history, games, utc_now()), utc_now().astimezone(EASTERN).date().isoformat()
    )
    candidates = filter_candidate_rows(path, candidates)
    rows = [
        row
        for row in candidates
        if row["stat"] in stats
        and row["probability"] >= threshold
        and (side == "Ambos" or row["side"] == side)
    ]
    if compact:
        seen = set()
        unique = []
        # A abertura mostra mercados diferentes, sem repetir o mesmo atleta nos três cartões.
        for stat in PROP_LABELS:
            candidate = next((r for r in rows if r["stat"] == stat and r["player_id"] not in seen), None)
            if candidate is not None:
                seen.add(candidate["player_id"])
                unique.append(candidate)
        for row in rows:
            if row["player_id"] not in seen:
                seen.add(row["player_id"])
                unique.append(row)
        rows = unique
    if not rows:
        st.info(
            "Nenhuma oportunidade atende aos filtros com os dados disponíveis. "
            "O painel não usa partidas antigas ou estatísticas ao vivo desatualizadas."
        )
    limit = 3 if compact else 9
    for start in range(0, min(len(rows), limit), 3):
        for column, row in zip(st.columns(min(3, len(rows) - start)), rows[start : start + 3], strict=False):
            with column:
                _prop_card(row)
    if compact:
        page_link("opportunities", "Abrir Over / Under e jogos ao vivo")
    elif rows:
        frame = pd.DataFrame(rows)
        st.download_button(
            "Baixar análise (CSV)",
            frame.to_csv(index=False).encode("utf-8-sig"),
            file_name="oportunidades_nba.csv",
            mime="text/csv",
            key=prefix + "_download",
        )
    if status.get("rejected_games"):
        st.caption("Alguns boxscores ainda aguardam validação. Consulte Fontes para os detalhes.")
