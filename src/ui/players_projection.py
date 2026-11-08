"""Aba Projeções da página Jogadores."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data import available_teams, team_snapshot
from src.nba_schedule import get_next_game_for_team
from src.nba_teams import TEAM_ABBREVIATION_TO_NAME
from src.player_features import (
    season_start_year,
)
from src.player_metrics import player_snapshot
from src.player_model import (
    over_probability,
    predict_player_game,
    range_probabilities,
)
from src.store import log_player_prediction
from src.ui import components, states


def projection_tab(
    _load_nba_schedule,
    _train_projection_bundle,
    player_games,
    player_id_by_label,
    player_options,
    players,
    source,
    team_games,
) -> None:
    """Aba Projeções."""
    if not components.load_on_demand(
        "Carregar projeções",
        key=f"player_projections_enabled_{source}",
        description="As projeções são preparadas sob demanda. Carregue quando quiser estimar o próximo jogo.",
    ):
        st.stop()
    st.caption(
        "A média da temporada mais recente disponível é a referência inicial para "
        "pontos, rebotes e assistências. A projeção ajusta essa base conforme minutos, "
        "forma recente, contexto do adversário e jogos já disputados na passagem pelo "
        "time atual. A referência perde peso gradualmente quando há evidências de uma "
        "nova função. Não usa informação confirmada de lesões ou disponibilidade dos companheiros."
    )

    try:
        bundle = _train_projection_bundle(player_games, team_games)
    except ValueError as error:
        st.warning(str(error))
        st.stop()

    projection_selection = st.selectbox(
        "Selecione um jogador",
        player_options,
        index=0,
        key=f"projection_player_select_{source}",
    )
    projection_id = player_id_by_label[projection_selection]

    known_seasons = (
        player_games["season"].dropna().astype(str).unique().tolist()
        if "season" in player_games.columns
        else []
    )
    known_years = [season_start_year(value) for value in known_seasons]
    known_years = [int(year) for year in known_years if pd.notna(year)]
    now = pd.Timestamp.now()
    current_season_start = now.year if now.month >= 7 else now.year - 1
    default_target_start = max([current_season_start, *known_years])
    default_target_season = f"{default_target_start}-{str(default_target_start + 1)[-2:]}"
    next_target_start = default_target_start + 1
    target_season_options = [
        default_target_season,
        f"{next_target_start}-{str(next_target_start + 1)[-2:]}",
    ]
    target_season = st.selectbox(
        "Temporada-alvo da previsão",
        target_season_options,
        index=0,
        help=(
            "A referência estatística será a temporada imediatamente anterior à escolhida. "
            "Se essa temporada não existir na base, o sistema usa a temporada histórica mais recente."
        ),
    )

    # Identifica automaticamente o próximo jogo pelo calendário oficial da NBA.
    # A última equipe vista no histórico serve apenas como sugestão: após uma
    # troca na offseason, o usuário pode selecionar manualmente a equipe atual.
    projection_history = player_games[player_games["player_id"] == projection_id].sort_values("game_date")
    historical_team = (
        str(projection_history.iloc[-1]["team"]).strip().upper() if not projection_history.empty else ""
    )
    schedule_team_code: str | None = None
    next_game: dict | None = None
    scheduled_opponent_name: str | None = None
    schedule_error: str | None = None

    if source == "real":
        team_codes = sorted(TEAM_ABBREVIATION_TO_NAME)
        team_default_index = team_codes.index(historical_team) if historical_team in team_codes else 0
        schedule_team_code = st.selectbox(
            "Equipe atual para localizar o próximo jogo",
            team_codes,
            index=team_default_index,
            format_func=lambda code: f"{code} — {TEAM_ABBREVIATION_TO_NAME[code]}",
            key=f"next_game_team_{source}_{projection_id}",
            help=(
                "A equipe histórica é selecionada por padrão. Se o jogador mudou de time "
                "nesta offseason e ainda não há jogos dele pela nova equipe na base, "
                "escolha aqui a equipe atual para procurar o confronto correto."
            ),
        )
        retry_state_key = f"nba_schedule_retry_token_{source}"
        if st.button("Atualizar calendário oficial", key=f"refresh_nba_schedule_{source}_{projection_id}"):
            st.session_state[retry_state_key] = int(st.session_state.get(retry_state_key, 0)) + 1
        retry_token = int(st.session_state.get(retry_state_key, 0))
        with st.spinner("Consultando o calendário oficial da NBA…"):
            official_schedule, schedule_error = _load_nba_schedule(retry_token, schedule_team_code)
        if schedule_error is None:
            next_game = get_next_game_for_team(official_schedule, schedule_team_code)

        if next_game is not None:
            scheduled_opponent_name = str(next_game["opponent_name"])
            schedule_day = next_game["game_date"]
            home_away_text = "em casa" if next_game["is_home_for_team"] else "fora de casa"
            kickoff = pd.to_datetime(next_game.get("game_datetime_utc"), errors="coerce", utc=True)
            kickoff_text = (
                f" às {kickoff.tz_convert('America/New_York').strftime('%H:%M')} ET"
                if pd.notna(kickoff)
                else ""
            )
            source_label = str(next_game.get("schedule_source", "NBA oficial"))
            st.success(
                f"Próximo confronto encontrado ({source_label}): "
                f"**{TEAM_ABBREVIATION_TO_NAME[schedule_team_code]} "
                f"x {scheduled_opponent_name}**, {schedule_day.strftime('%d/%m/%Y')} "
                f"({home_away_text}){kickoff_text}. A previsão será calculada para esse jogo."
            )
        elif schedule_error:
            st.warning(
                "Não foi possível consultar automaticamente o calendário nas fontes disponíveis. "
                "Preencha o adversário e a data manualmente ou tente novamente em outra conexão."
            )
            st.caption(
                "Se a mensagem persistir, verifique se o firewall, antivírus, proxy ou a rede da empresa "
                "permite conexões HTTPS com os serviços de calendário esportivo."
            )
            st.info(
                "A data sugerida abaixo é apenas uma data manual inicial — não é um jogo confirmado. "
                "Antes de interpretar a projeção como previsão do próximo confronto, confirme a partida "
                "em um calendário atualizado e selecione o adversário correto."
            )
        else:
            st.info(
                "Não encontrei um jogo futuro para essa equipe no período consultado. "
                "Confira a equipe selecionada ou informe o cenário manualmente."
            )
            st.caption(
                "A data sugerida abaixo não deve ser interpretada como confronto confirmado. "
                "Verifique o calendário antes de usar a projeção como previsão do próximo jogo."
            )
    else:
        st.info(
            "A base demonstrativa contém jogadores sintéticos; por isso, não é possível "
            "associá-los automaticamente à agenda real da NBA. Use os campos manuais abaixo."
        )

    schedule_target_date = next_game["game_date"] if next_game else date.today() + timedelta(days=1)
    is_home_default = bool(next_game["is_home_for_team"]) if next_game else True
    last_history_date = (
        pd.Timestamp(projection_history.iloc[-1]["game_date"]).date()
        if not projection_history.empty
        else date.today()
    )
    calendar_gap = max(0, (schedule_target_date - last_history_date).days - 1)
    rest_days_default = min(7, calendar_gap)
    if calendar_gap > 14:
        st.warning(
            "A base não contém jogos recentes suficientes deste jogador para o confronto selecionado. "
            "A projeção se apoia em histórico antigo e pode não refletir a rotação, "
            "os minutos ou a função atual. "
            "Execute a atualização dos dados antes de confiar nesta estimativa."
        )

    col_home, col_rest, col_opponent, col_target_date = st.columns(4)
    with col_home:
        is_home = (
            st.radio(
                "Mando de quadra",
                ["Casa", "Fora"],
                index=0 if is_home_default else 1,
                horizontal=True,
                key=f"projection_home_{source}_{projection_id}_{schedule_team_code or 'manual'}",
            )
            == "Casa"
        )
    with col_rest:
        rest_days = st.number_input(
            "Dias de descanso",
            0,
            7,
            rest_days_default,
            key=f"projection_rest_{source}_{projection_id}_{schedule_team_code or 'manual'}",
            help="Estimado pela diferença entre a data do último jogo disponível e a data-alvo.",
        )
    with col_opponent:
        opponent_def_rating: float | None = None
        available_opponent_names = (
            available_teams(team_games) if team_games is not None and not team_games.empty else []
        )
        opponent_options = list(available_opponent_names)
        if scheduled_opponent_name and scheduled_opponent_name not in opponent_options:
            opponent_options.append(scheduled_opponent_name)
        opponent_options = sorted(set(opponent_options))
        if opponent_options:
            opponent_choices = list(opponent_options)
            if source == "real" and next_game is None:
                opponent_choices = ["Selecione manualmente"] + opponent_choices
            default_opponent_index = (
                opponent_choices.index(scheduled_opponent_name)
                if scheduled_opponent_name in opponent_choices
                else 0
            )
            selected_opponent_value = st.selectbox(
                "Próximo adversário",
                opponent_choices,
                index=default_opponent_index,
                key=f"projection_opponent_{source}_{projection_id}_{schedule_team_code or 'manual'}",
            )
            selected_opponent = (
                None if selected_opponent_value == "Selecione manualmente" else selected_opponent_value
            )
            if (
                selected_opponent is not None
                and team_games is not None
                and selected_opponent in available_opponent_names
            ):
                try:
                    opponent_def_rating = team_snapshot(
                        team_games, selected_opponent, with_elo=False
                    )["def_rating"]
                except ValueError:
                    opponent_def_rating = None
            if selected_opponent is not None and opponent_def_rating is None:
                st.caption(
                    "Rating defensivo específico não encontrado na base; a previsão usará "
                    "a referência média da liga para este fator."
                )
        else:
            selected_opponent = (
                st.text_input(
                    "Próximo adversário",
                    value=scheduled_opponent_name or "",
                    key=f"projection_opponent_text_{source}_{projection_id}_{schedule_team_code or 'manual'}",
                    placeholder="Ex.: Boston Celtics",
                ).strip()
                or None
            )
    with col_target_date:
        target_game_date = st.date_input(
            "Data do jogo previsto",
            value=schedule_target_date,
            format="DD/MM/YYYY",
            help=(
                "Quando o calendário oficial está disponível, este campo começa na data do próximo jogo. "
                "Você pode alterá-la manualmente para simular outro confronto."
            ),
            key=f"target_game_date_{source}_{projection_id}_{schedule_team_code or 'manual'}",
        )

    if next_game and target_game_date != next_game["game_date"]:
        st.warning(
            "A data escolhida é diferente da data do próximo jogo encontrado. "
            "A projeção será registrada para a data escolhida; confirme o adversário e o mando."
        )

    snapshot = player_snapshot(player_games, projection_id, target_season=target_season)
    prediction = predict_player_game(
        bundle,
        snapshot,
        is_home=is_home,
        rest_days=rest_days,
        opponent_def_rating=opponent_def_rating,
    )

    projection_games_played = int((player_games["player_id"] == projection_id).sum())
    states.small_sample_warning(projection_games_played, threshold=15)

    st.markdown("#### Projeção do próximo jogo")
    projection_metrics = st.columns(4)
    projection_metrics[0].metric("Minutos", f"{prediction.minutes:.1f}")
    projection_metrics[1].metric("Pontos", f"{prediction.stats['pts']:.1f}")
    projection_metrics[2].metric("Rebotes", f"{prediction.stats['reb']:.1f}")
    projection_metrics[3].metric("Assistências", f"{prediction.stats['ast']:.1f}")

    baseline_label = snapshot.get("prev_season_label", "histórico disponível")
    st.markdown(f"#### Comparação com a temporada-base ({baseline_label})")
    baseline_columns = st.columns(3)
    baseline_descriptions = (
        ("pts", "Pontos", "prev_season_pts_avg"),
        ("reb", "Rebotes", "prev_season_reb_avg"),
        ("ast", "Assistências", "prev_season_ast_avg"),
    )
    for column, (stat, label, baseline_key) in zip(baseline_columns, baseline_descriptions, strict=True):
        baseline_value = float(snapshot.get(baseline_key, 0.0))
        projected_value = float(prediction.stats[stat])
        column.metric(
            f"Média-base — {label}",
            f"{baseline_value:.1f}",
            delta=f"{projected_value - baseline_value:+.1f} na projeção",
            delta_color="normal",
        )
    st.caption(
        "O baseline é a média por jogo da temporada mais recente disponível nos dados. "
        "A estimativa usa também a taxa por minuto dessa temporada para ajustar os "
        "resultados aos minutos previstos. Após uma troca de time, a referência anual "
        "tem maior peso no início e diminui conforme chegam partidas do novo stint."
    )

    if st.button("Registrar esta previsão", type="primary"):
        projection_player_name = players.loc[players["player_id"] == projection_id, "player_name"].iloc[0]
        log_player_prediction(
            projection_id,
            projection_player_name,
            selected_opponent,
            is_home,
            prediction.minutes,
            prediction.stats["pts"],
            prediction.stats["reb"],
            prediction.stats["ast"],
            prediction.confidence,
            target_game_date=target_game_date.isoformat(),
        )
        st.success(
            f"Previsão registrada para {target_game_date.strftime('%d/%m/%Y')}. "
            "Acompanhe em 'Desempenho': ela só será resolvida quando houver dados "
            "do jogador para a data-alvo e o contexto de adversário/mando coincidir."
        )

    st.markdown("###### Como a projeção de pontos foi montada")
    chain_columns = st.columns(4)
    chain_columns[0].metric("Pontos — modelo direto", f"{prediction.stats['pts']:.1f}")
    chain_columns[1].metric("Referência FGA × TS%", f"{prediction.chain_pts:.1f}")
    chain_columns[2].metric("Arremessos previstos (FGA)", f"{prediction.projected_fga:.1f}")
    chain_columns[3].metric("Aproveitamento previsto (TS%)", f"{prediction.projected_ts_pct:.1%}")
    st.caption(
        "A projeção principal usa um regressor direto de pontos por minuto × minutos esperados, "
        "com histórico recente, volume ofensivo, eficiência, rotação e contexto. A conta FGA × TS% "
        "é exibida como referência interpretável independente; lances livres nessa referência usam "
        "a proporção histórica do próprio jogador (FTA/FGA)."
    )

    interval_data = pd.DataFrame(
        {
            "Estatística": ["Pontos", "Rebotes", "Assistências"],
            "Mínimo": [
                prediction.stats_low["pts"],
                prediction.stats_low["reb"],
                prediction.stats_low["ast"],
            ],
            "Central": [
                prediction.stats["pts"],
                prediction.stats["reb"],
                prediction.stats["ast"],
            ],
            "Máximo": [
                prediction.stats_high["pts"],
                prediction.stats_high["reb"],
                prediction.stats_high["ast"],
            ],
        }
    )
    st.dataframe(
        interval_data.style.format({"Mínimo": "{:.1f}", "Central": "{:.1f}", "Máximo": "{:.1f}"}),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        f"Confiança do modelo: {prediction.confidence}. "
        "É uma classe de incerteza relativa baseada no erro histórico, quantidade de histórico "
        "e estabilidade do stint — não uma probabilidade de acerto. O intervalo é experimental "
        "e sua cobertura deve ser acompanhada na auditoria das previsões resolvidas."
    )

    st.markdown("#### Probabilidade de over/under")
    stat_labels = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}
    col_stat, col_line = st.columns(2)
    with col_stat:
        over_under_stat = st.selectbox(
            "Estatística", list(stat_labels.keys()), format_func=lambda key: stat_labels[key]
        )
    with col_line:
        default_line = round(prediction.stats[over_under_stat] * 2) / 2
        line = st.number_input("Line", value=default_line, step=0.5)

    over_pct = over_probability(prediction.stats[over_under_stat], bundle.residual_std[over_under_stat], line)
    over_under_columns = st.columns(2)
    over_under_columns[0].metric(f"Over {line:g}", f"{over_pct:.0%}")
    over_under_columns[1].metric(f"Under {line:g}", f"{1 - over_pct:.0%}")
    st.caption(
        "Probabilidade estatística calculada a partir da previsão do modelo e do seu erro "
        "histórico (assumindo distribuição normal em torno da previsão) — não é uma odds de "
        "mercado nem orientação de aposta; o projeto não usa odds."
    )

    st.markdown("#### Distribuição de resultados")
    buckets = range_probabilities(prediction.stats[over_under_stat], bundle.residual_std[over_under_stat])
    distribution_figure = go.Figure(
        go.Bar(
            x=[bucket["label"] for bucket in buckets],
            y=[bucket["probability"] for bucket in buckets],
            text=[f"{bucket['probability']:.0%}" for bucket in buckets],
            textposition="outside",
            marker_color="#d9560f",
        )
    )
    distribution_figure.update_layout(
        yaxis_tickformat=".0%",
        yaxis_title="Probabilidade",
        xaxis_title=stat_labels[over_under_stat],
        height=320,
        margin=dict(t=10, b=10),
    )
    st.plotly_chart(distribution_figure, use_container_width=True)
    st.caption(
        "Faixas geradas a partir da própria previsão: largura = erro histórico do modelo "
        "arredondado (mínimo 1), 5 faixas centradas na projeção. Mesma aproximação normal do "
        "over/under acima, fatiada em vários pontos de corte."
    )

    st.markdown("#### Qualidade do modelo (erro médio absoluto)")
    quality_metrics = st.columns(4)
    quality_metrics[0].metric("Minutos", f"{bundle.metrics['minutes_mae']:.1f}")
    quality_metrics[1].metric("Pontos", f"{bundle.metrics['pts_mae']:.1f}")
    quality_metrics[2].metric("Rebotes", f"{bundle.metrics['reb_mae']:.1f}")
    quality_metrics[3].metric("Assistências", f"{bundle.metrics['ast_mae']:.1f}")
