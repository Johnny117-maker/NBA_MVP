from __future__ import annotations

import streamlit as st

from src.store import (
    DEFAULT_DB_PATH,
    count_games,
    count_player_games,
    read_player_games,
    read_player_predictions,
    read_raw_games,
    read_team_predictions,
    resolve_player_predictions,
    resolve_team_predictions,
)
from src.ui import theme

st.set_page_config(
    page_title="Desempenho — NBA Analytics Lab",
    page_icon="📈",
    layout="wide",
)

theme.inject_base_style()

st.markdown("## 📈 Desempenho do modelo")
st.caption(
    "Previsões de times e de jogadores registradas manualmente (botão 'Registrar esta "
    "previsão' na página inicial e na aba Projeções de Jogadores), comparadas com o "
    "resultado real quando ele acontece."
)
st.caption("📊 Erros, calibração e histórico de retreinamento ficam em 'Qualidade do Modelo', na barra lateral.")

tab_team_predictions, tab_player_predictions = st.tabs(["Previsões de times", "Previsões de jogadores"])

with tab_team_predictions:
    predictions = read_team_predictions(DEFAULT_DB_PATH)

    if predictions.empty:
        st.info(
            "Nenhuma previsão registrada ainda. Vá até a página inicial, gere uma "
            "previsão de times e clique em 'Registrar esta previsão'."
        )
    else:
        real_data_available = count_games(DEFAULT_DB_PATH) > 0
        if st.button("Resolver previsões com jogos reais", disabled=not real_data_available):
            games = read_raw_games(DEFAULT_DB_PATH)
            resolved_now = resolve_team_predictions(games, DEFAULT_DB_PATH)
            st.success(f"{resolved_now} previsão(ões) resolvida(s) com jogos reais.")
            predictions = read_team_predictions(DEFAULT_DB_PATH)
        if not real_data_available:
            st.caption(
                "Resolver exige dados reais coletados ('python scripts/update_data.py')."
            )

        resolved = predictions[predictions["resolved_at"].notna()].copy()
        pending = predictions[predictions["resolved_at"].isna()]

        summary_columns = st.columns(3)
        summary_columns[0].metric("Previsões registradas", len(predictions))
        summary_columns[1].metric("Resolvidas", len(resolved))
        summary_columns[2].metric("Pendentes", len(pending))

        if not resolved.empty:
            resolved["predicted_home_win"] = resolved["home_win_probability"] >= 0.5
            resolved["actual_home_win"] = resolved["actual_home_score"] > resolved["actual_away_score"]
            resolved["correct_winner"] = resolved["predicted_home_win"] == resolved["actual_home_win"]
            resolved["home_score_error"] = (
                resolved["predicted_home_score"] - resolved["actual_home_score"]
            ).abs()
            resolved["away_score_error"] = (
                resolved["predicted_away_score"] - resolved["actual_away_score"]
            ).abs()

            accuracy_columns = st.columns(3)
            accuracy_columns[0].metric(
                "Accuracy (vencedor)", f"{resolved['correct_winner'].mean():.1%}"
            )
            accuracy_columns[1].metric(
                "MAE placar mandante", f"{resolved['home_score_error'].mean():.1f}"
            )
            accuracy_columns[2].metric(
                "MAE placar visitante", f"{resolved['away_score_error'].mean():.1f}"
            )

            st.markdown("#### Calibração (probabilidade prevista vs. taxa real de vitória)")
            resolved["probability_bucket"] = (resolved["home_win_probability"] * 10).astype(int) * 10
            calibration = resolved.groupby("probability_bucket").agg(
                previsoes=("correct_winner", "count"),
                taxa_real_vitoria_mandante=("actual_home_win", "mean"),
            )
            st.dataframe(
                calibration.style.format({"taxa_real_vitoria_mandante": "{:.1%}"}),
                use_container_width=True,
            )
            st.caption(
                "Em uma previsão bem calibrada, o time favorecido a 70% deve vencer "
                "aproximadamente 7 em cada 10 vezes em situações parecidas."
            )

        st.markdown("#### Todas as previsões")
        display = predictions.rename(
            columns={
                "created_at": "Registrada em",
                "home_team": "Mandante",
                "away_team": "Visitante",
                "home_win_probability": "Prob. mandante",
                "predicted_home_score": "Placar previsto (M)",
                "predicted_away_score": "Placar previsto (V)",
                "confidence": "Confiança",
                "actual_home_score": "Placar real (M)",
                "actual_away_score": "Placar real (V)",
                "resolved_at": "Resolvida em",
            }
        )
        st.dataframe(
            display.style.format(
                {"Prob. mandante": "{:.1%}", "Placar previsto (M)": "{:.0f}", "Placar previsto (V)": "{:.0f}"},
                na_rep="—",
            ),
            hide_index=True,
            use_container_width=True,
        )

with tab_player_predictions:
    player_predictions = read_player_predictions(DEFAULT_DB_PATH)

    if player_predictions.empty:
        st.info(
            "Nenhuma previsão de jogador registrada ainda. Vá até a página 'Jogadores', "
            "aba 'Projeções', gere uma previsão e clique em 'Registrar esta previsão'."
        )
    else:
        real_player_data_available = count_player_games(DEFAULT_DB_PATH) > 0
        if st.button(
            "Resolver previsões com jogos reais",
            disabled=not real_player_data_available,
            key="resolve_player_predictions",
        ):
            player_games = read_player_games(DEFAULT_DB_PATH)
            resolved_now = resolve_player_predictions(player_games, DEFAULT_DB_PATH)
            st.success(f"{resolved_now} previsão(ões) resolvida(s) com jogos reais.")
            player_predictions = read_player_predictions(DEFAULT_DB_PATH)
        if not real_player_data_available:
            st.caption(
                "Resolver exige dados reais de jogadores coletados "
                "('python scripts/update_data.py')."
            )
        st.caption(
            "A resolução casa cada previsão com o próximo jogo real do mesmo jogador, "
            "não com o adversário escolhido na hora da previsão — o adversário ali é "
            "hipotético, não vem de uma agenda real de jogos futuros."
        )

        resolved = player_predictions[player_predictions["resolved_at"].notna()].copy()
        pending = player_predictions[player_predictions["resolved_at"].isna()]

        summary_columns = st.columns(3)
        summary_columns[0].metric("Previsões registradas", len(player_predictions))
        summary_columns[1].metric("Resolvidas", len(resolved))
        summary_columns[2].metric("Pendentes", len(pending))

        if not resolved.empty:
            resolved["minutes_error"] = (resolved["predicted_minutes"] - resolved["actual_minutes"]).abs()
            resolved["pts_error"] = (resolved["predicted_pts"] - resolved["actual_pts"]).abs()
            resolved["reb_error"] = (resolved["predicted_reb"] - resolved["actual_reb"]).abs()
            resolved["ast_error"] = (resolved["predicted_ast"] - resolved["actual_ast"]).abs()

            error_columns = st.columns(4)
            error_columns[0].metric("MAE minutos", f"{resolved['minutes_error'].mean():.1f}")
            error_columns[1].metric("MAE pontos", f"{resolved['pts_error'].mean():.1f}")
            error_columns[2].metric("MAE rebotes", f"{resolved['reb_error'].mean():.1f}")
            error_columns[3].metric("MAE assistências", f"{resolved['ast_error'].mean():.1f}")

        st.markdown("#### Todas as previsões")
        display = player_predictions.rename(
            columns={
                "created_at": "Registrada em",
                "player_name": "Jogador",
                "opponent": "Adversário (hipotético)",
                "is_home": "Casa",
                "predicted_minutes": "Minutos previstos",
                "predicted_pts": "Pontos previstos",
                "predicted_reb": "Rebotes previstos",
                "predicted_ast": "Assistências previstas",
                "confidence": "Confiança",
                "actual_minutes": "Minutos reais",
                "actual_pts": "Pontos reais",
                "actual_reb": "Rebotes reais",
                "actual_ast": "Assistências reais",
                "resolved_at": "Resolvida em",
            }
        ).drop(columns=["id", "player_id"])
        st.dataframe(
            display.style.format(
                {
                    "Minutos previstos": "{:.1f}",
                    "Pontos previstos": "{:.1f}",
                    "Rebotes previstos": "{:.1f}",
                    "Assistências previstas": "{:.1f}",
                },
                na_rep="—",
            ),
            hide_index=True,
            use_container_width=True,
        )
