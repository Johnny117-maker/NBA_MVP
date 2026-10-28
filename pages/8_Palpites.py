from __future__ import annotations

import pandas as pd
import streamlit as st

from src.daily_games import games_for_date, today_et
from src.round_context import _form_table, _load_schedule, _project_player, _team_model_context
from src.schedule_storage import DEFAULT_SCHEDULE_CACHE_PATH
from src.store import DEFAULT_DB_PATH, count_player_games
from src.today_picks import build_matchup_pick, round_highlights, upcoming_games
from src.ui import components, theme
from src.ui.archive import archived_preview
from src.ui.formatters import format_date_br
from src.ui.navigation import page_link
from src.ui.round_cards import highlights_grid, history_notice, matchup_strip

st.set_page_config(page_title="Palpites de Hoje — NBA Analytics Lab", page_icon="✨", layout="wide")
theme.inject_base_style("picks")
components.page_header(
    "Os nomes e as tendências de hoje.",
    "Escolha os atletas para acompanhar e consulte as projeções dos confrontos que ainda vão começar.",
    category="PALPITES DE HOJE",
)

today = today_et()
archived_preview(DEFAULT_DB_PATH, today.isoformat(), "picks_archive")
day_column, refresh_column = st.columns([3, 1])
with day_column:
    st.markdown(f"**{format_date_br(today)} · calendário NBA (ET)**")
with refresh_column:
    if st.button("Atualizar jogos de hoje"):
        st.session_state["daily_schedule_retry"] = int(st.session_state.get("daily_schedule_retry", 0)) + 1

schedule, schedule_error = _load_schedule(int(st.session_state.get("daily_schedule_retry", 0)), today)
day_games = games_for_date(schedule, today)
if schedule_error or day_games.empty:
    manual = games_for_date(
        pd.DataFrame(list(st.session_state.get("manual_daily_games", {}).values())), today
    )
    if not manual.empty:
        day_games = pd.concat([day_games, manual], ignore_index=True).drop_duplicates(
            ["game_date", "home_team_tricode", "away_team_tricode"],
            keep="last",
        )
if schedule_error:
    st.warning(
        "As fontes do calendário não responderam. A lista usa apenas o calendário salvo ou confrontos "
        "cadastrados na sessão; horários e status precisam ser conferidos."
    )

games = upcoming_games(day_games, today, pd.Timestamp.now(tz="UTC"))
if games.empty:
    st.info(
        "Nenhum jogo de hoje disponível para novos palpites. A lista exclui partidas em andamento, "
        "encerradas, adiadas ou cujo horário de início conhecido já passou."
    )
    page_link("games", "Consultar a rodada ou informar um confronto")
    st.stop()

with st.expander("Fontes e critérios desta seleção"):
    source = ", ".join(games["schedule_source"].dropna().astype(str).unique())
    components.source_badge(f"Calendário — {source}", components.db_last_updated(DEFAULT_SCHEDULE_CACHE_PATH))
    st.caption(
        "O dia segue o fuso da costa leste dos EUA. O arquivo público tem atualização periódica. "
        "Só entram jogos agendados com início futuro, ou horário ainda não informado. "
        "Elencos e lesões não são confirmados; as equipes dos atletas vêm do histórico local."
    )
    if games["schedule_source"].fillna("").str.startswith("SportsDataverse").any():
        st.markdown(
            "Calendário: [SportsDataverse / hoopR](https://github.com/sportsdataverse/hoopR-nba-data), "
            "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)."
        )

db_path = str(DEFAULT_DB_PATH)
version = DEFAULT_DB_PATH.stat().st_mtime if DEFAULT_DB_PATH.exists() else 0.0
form = pd.DataFrame()
if DEFAULT_DB_PATH.exists() and count_player_games(DEFAULT_DB_PATH):
    try:
        form = _form_table(db_path, version, "historical-fallback", (), today)
    except (ValueError, FileNotFoundError, KeyError):
        st.info("Histórico de jogadores indisponível. Os palpites dos times continuam acessíveis.")
history_notice(form, today)

try:
    bundle, team_history = _team_model_context(db_path, version, today)
except (ValueError, FileNotFoundError, KeyError):
    bundle, team_history = None, pd.DataFrame()

components.metric_row(
    [
        {"label": "Jogos para analisar", "value": str(len(games))},
        {
            "label": "Equipes na rodada",
            "value": str(len(set(games["home_team_tricode"].tolist() + games["away_team_tricode"].tolist()))),
        },
        {"label": "Data dos palpites", "value": format_date_br(today)},
    ]
)
tab_players, tab_teams = st.tabs(["Palpites de jogadores", "Palpites dos confrontos"])

with tab_teams, st.container(key="today_team_picks"):
    components.section_header(
        "Preferências do modelo", "Vencedor estimado, placar central e fatores do confronto."
    )
    if bundle is None:
        st.info("Palpites de times indisponíveis: colete pelo menos 50 jogos com histórico das equipes.")
        page_link("data", "Atualizar a base")
    else:
        export_rows = []
        for start in range(0, len(games), 2):
            for column, (_, game) in zip(
                st.columns(2), games.iloc[start : start + 2].iterrows(), strict=False
            ):
                with column, st.container(border=True):
                    matchup_strip(game)
                    try:
                        pick = build_matchup_pick(bundle, team_history, game, today)
                    except (ValueError, KeyError, TypeError, OverflowError):
                        st.info("Histórico insuficiente para projetar este confronto.")
                        continue
                    st.caption(
                        "Confronto equilibrado" if pick.probability < 0.53 else "Preferência do modelo"
                    )
                    st.markdown(f"### {pick.favorite}")
                    st.progress(pick.probability)
                    components.metric_row(
                        [
                            {"label": "Chance estimada", "value": f"{pick.probability:.0%}"},
                            {
                                "label": "Placar · fora × casa",
                                "value": (
                                    f"{pick.prediction.away_score:.0f} × {pick.prediction.home_score:.0f}"
                                ),
                            },
                        ]
                    )
                    st.caption(
                        f"Confiança: {pick.confidence} · "
                        f"histórico das equipes até {pick.last_game_date:%d/%m/%Y}."
                    )
                    for factor, impact in sorted(
                        pick.prediction.factors, key=lambda item: abs(item[1]), reverse=True
                    )[:2]:
                        side = game["home_team_name"] if impact >= 0 else game["away_team_name"]
                        st.caption(f"• {factor}: favorece {side}.")
                    with st.expander("Faixas de placar"):
                        st.write(
                            f"Visitante: {pick.prediction.away_score_low:.0f}–"
                            f"{pick.prediction.away_score_high:.0f} pts. "
                            f"Mandante: {pick.prediction.home_score_low:.0f}–"
                            f"{pick.prediction.home_score_high:.0f} pts."
                        )
                        st.caption(
                            "Intervalos experimentais de aproximadamente 80%, baseados no erro histórico."
                        )
                    export_rows.append(
                        {
                            "data_ET": today.isoformat(),
                            "confronto": f"{game['away_team_name']} @ {game['home_team_name']}",
                            "preferencia": pick.favorite,
                            "probabilidade_modelo": pick.probability,
                            "placar_visitante": pick.prediction.away_score,
                            "placar_mandante": pick.prediction.home_score,
                            "confianca": pick.confidence,
                            "historico_ate": str(pick.last_game_date.date()),
                            "fonte_calendario": game["schedule_source"],
                        }
                    )
        if export_rows:
            st.download_button(
                "Baixar palpites dos confrontos (CSV)",
                pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8-sig"),
                file_name=f"palpites_nba_{today.isoformat()}.csv",
                mime="text/csv",
            )
        st.caption(
            "Probabilidades experimentais do modelo de Times. A maior probabilidade não garante o resultado."
        )

with tab_players, st.container(key="today_player_picks"):
    components.section_header(
        "Os protagonistas da rodada", "Projeções de pontos, rebotes e assistências, caso o atleta participe."
    )
    per_team = st.selectbox("Destaques por equipe para projetar", [1, 2, 3])
    candidates = round_highlights(form, games, top_n=per_team)
    if candidates.empty:
        st.info(
            "Sem jogadores elegíveis para estes jogos. "
            "Atualize as estatísticas para gerar palpites individuais."
        )
        page_link("data", "Coletar estatísticas de jogadores")
    else:
        st.caption(
            f"{len(candidates)} atletas selecionados por impacto recente. "
            "A geração inicial pode levar alguns instantes."
        )
        activation = f"today_picks_players_{db_path}_{version}_{today.isoformat()}_{per_team}"
        if st.button("Gerar palpites de jogadores", type="primary"):
            st.session_state[activation] = True
        if not st.session_state.get(activation, False):
            st.caption("Prévia: médias das últimas até cinco partidas, ainda sem projeção do modelo.")
            highlights_grid(candidates)
        else:
            active_ids = set(upcoming_games(games, today, pd.Timestamp.now(tz="UTC"))["game_id"].astype(str))
            for start in range(0, len(candidates), 2):
                for column, (_, player) in zip(
                    st.columns(2),
                    candidates.iloc[start : start + 2].iterrows(),
                    strict=False,
                ):
                    with column, st.container(border=True):
                        st.caption(str(player["matchup"]))
                        st.markdown(f"### {player['player_name']}")
                        if str(player["game_id"]) not in active_ids:
                            st.info("O horário deste jogo já passou. Atualize a rodada.")
                            continue
                        if int(player["recent_games"]) < 3:
                            st.info("Amostra recente insuficiente: são necessárias ao menos três partidas.")
                            continue
                        last_date = pd.Timestamp(player["last_game_date"])
                        rest_days = min(7, max(1, (today - last_date.date()).days))
                        try:
                            with st.spinner("Preparando a projeção do jogador…"):
                                projection = _project_player(
                                    db_path,
                                    version,
                                    int(player["player_id"]),
                                    str(player["opponent_name"]),
                                    bool(player["is_home"]),
                                    rest_days,
                                    today,
                                )
                        except (ValueError, FileNotFoundError, KeyError):
                            projection = None
                        except MemoryError:
                            st.session_state[activation] = False
                            st.error(
                                "Memória insuficiente para preparar o modelo nesta sessão. "
                                "As médias dos destaques continuam disponíveis; feche aplicações "
                                "pesadas ou reinicie o servidor antes de tentar novamente."
                            )
                            st.stop()
                        if projection is None:
                            st.info("Não foi possível gerar uma projeção com o histórico disponível.")
                            continue
                        confidence = (
                            "Baixa · histórico antigo"
                            if (today - last_date.date()).days > 14
                            else projection["confidence"]
                        )
                        components.metric_row(
                            [
                                {"label": label, "value": f"{projection[stat]:.1f}"}
                                for stat, label in (
                                    ("pts", "Pontos"),
                                    ("reb", "Rebotes"),
                                    ("ast", "Assistências"),
                                )
                            ]
                        )
                        st.caption(
                            f"Minutos estimados: {projection['minutes']:.1f} · Confiança: {confidence}. "
                            f"Último jogo: {last_date:%d/%m/%Y}."
                        )
                        with st.expander("Faixas e referência recente"):
                            training = projection["training"]
                            st.caption(
                                f"Treino: {training['rows']:,} linhas de jogadores, "
                                f"de {training['from']:%d/%m/%Y} a {training['to']:%d/%m/%Y}. "
                                "Janela recente limitada a 40 mil linhas, preservando datas completas."
                            )
                            for stat, label in (
                                ("pts", "Pontos"),
                                ("reb", "Rebotes"),
                                ("ast", "Assistências"),
                            ):
                                st.write(
                                    f"{label}: {projection['stats_low'][stat]:.1f}–"
                                    f"{projection['stats_high'][stat]:.1f} "
                                    f"· média recente: {player[f'{stat}_recent']:.1f}."
                                )
                            st.caption(
                                "Faixas experimentais; a confiança é uma classe de incerteza, "
                                "não taxa de acerto."
                            )

page_link("games", "Voltar aos jogadores e confrontos da rodada")
