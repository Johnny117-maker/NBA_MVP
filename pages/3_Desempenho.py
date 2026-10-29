from __future__ import annotations

import pandas as pd
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
from src.ui import components, theme
from src.ui.forecast_performance import performance_panel
from src.ui.navigation import page_link

st.set_page_config(
    page_title="Desempenho — NBA Analytics Lab",
    page_icon="📈",
    layout="wide",
)

theme.inject_base_style("performance")

view = st.segmented_control(
    "Origem das previsões",
    ["Palpites automáticos", "Registros manuais"],
    default="Palpites automáticos",
    required=True,
)
if view == "Palpites automáticos":
    performance_panel(DEFAULT_DB_PATH)
    st.stop()

components.page_header(
    "Da previsão ao resultado.",
    "Acompanhe as projeções que você salvou e veja como elas se comparam às partidas reais.",
    category="DESEMPENHO",
)
st.caption(
    "📊 Erros, calibração e histórico de retreinamento ficam em 'Qualidade do Modelo', na barra lateral."
)
components.source_badge("Previsões salvas neste projeto", components.db_last_updated(DEFAULT_DB_PATH))

tab_team_predictions, tab_player_predictions = st.tabs(["Previsões de times", "Previsões de jogadores"])

with tab_team_predictions:
    predictions = read_team_predictions(DEFAULT_DB_PATH)

    if predictions.empty:
        st.info(
            "Nenhuma previsão registrada ainda. Vá até a página Times, gere uma "
            "previsão de times e clique em 'Registrar esta previsão'."
        )
        page_link("teams", "Criar uma previsão de times")
    else:
        real_data_available = count_games(DEFAULT_DB_PATH) > 0
        if st.button("Resolver previsões com jogos reais", disabled=not real_data_available):
            games = read_raw_games(DEFAULT_DB_PATH)
            resolved_now = resolve_team_predictions(games, DEFAULT_DB_PATH)
            st.success(f"{resolved_now} previsão(ões) resolvida(s) com jogos reais.")
            predictions = read_team_predictions(DEFAULT_DB_PATH)
        if not real_data_available:
            st.caption("Resolver exige dados reais coletados ('python scripts/update_data.py').")

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
            accuracy_columns[0].metric("Accuracy (vencedor)", f"{resolved['correct_winner'].mean():.1%}")
            accuracy_columns[1].metric("MAE placar mandante", f"{resolved['home_score_error'].mean():.1f}")
            accuracy_columns[2].metric("MAE placar visitante", f"{resolved['away_score_error'].mean():.1f}")

            st.markdown("#### Calibração (probabilidade prevista vs. taxa real de vitória)")
            resolved["probability_bucket"] = (resolved["home_win_probability"] * 10).astype(int) * 10
            calibration = resolved.groupby("probability_bucket").agg(
                previsoes=("correct_winner", "count"),
                taxa_real_vitoria_mandante=("actual_home_win", "mean"),
            )
            st.dataframe(
                calibration.style.format({"taxa_real_vitoria_mandante": "{:.1%}"}),
                width="stretch",
            )
            st.caption(
                "Em uma previsão bem calibrada, o time favorecido a 70% deve vencer "
                "aproximadamente 7 em cada 10 vezes em situações parecidas."
            )

        components.section_header(
            "Histórico de previsões", "Registros, projeções e resultados no mesmo lugar."
        )
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
                {
                    "Prob. mandante": "{:.1%}",
                    "Placar previsto (M)": "{:.0f}",
                    "Placar previsto (V)": "{:.0f}",
                },
                na_rep="—",
            ),
            hide_index=True,
            width="stretch",
        )

with tab_player_predictions:
    player_predictions = read_player_predictions(DEFAULT_DB_PATH)

    if player_predictions.empty:
        st.info(
            "Nenhuma previsão de jogador registrada ainda. Vá até a página 'Jogadores', "
            "aba 'Projeções', gere uma previsão e clique em 'Registrar esta previsão'."
        )
        page_link("players", "Criar uma previsão de jogador")
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
            st.caption("Resolver exige dados reais de jogadores coletados ('python scripts/update_data.py').")
        st.caption(
            "Previsões novas são resolvidas apenas contra uma partida da data-alvo selecionada; "
            "adversário e mando também são conferidos quando esses dados estão disponíveis. "
            "Previsões antigas sem data-alvo tentam casar adversário e mando; somente registros "
            "legados sem esses campos usam a próxima partida disponível."
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

            # Comparação empírica das classes de confiança com resultados resolvidos.
            st.markdown("#### Auditoria da confiança")
            confidence_audit = (
                resolved.groupby("confidence", dropna=False)
                .agg(
                    previsoes=("id", "count"),
                    MAE_minutos=("minutes_error", "mean"),
                    MAE_pontos=("pts_error", "mean"),
                    MAE_rebotes=("reb_error", "mean"),
                    MAE_assistencias=("ast_error", "mean"),
                )
                .reindex(["Alta", "Média", "Baixa"])
                .dropna(how="all")
                .reset_index()
            )
            st.dataframe(
                confidence_audit.style.format(
                    {
                        "MAE_minutos": "{:.1f}",
                        "MAE_pontos": "{:.1f}",
                        "MAE_rebotes": "{:.1f}",
                        "MAE_assistencias": "{:.1f}",
                    },
                    na_rep="—",
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "A confiança é uma classe heurística de incerteza. Com poucos registros por "
                "classe, os erros médios são instáveis; a tabela acumula evidências ao longo "
                "das rodadas e ajuda a detectar quando previsões marcadas como 'Alta' erram mais."
            )

            st.markdown("#### Backtest por rodada/data do jogo")
            for column in ("target_game_date", "actual_game_date"):
                if column not in resolved.columns:
                    resolved[column] = pd.NaT
            resolved["audit_game_date"] = resolved["target_game_date"].combine_first(
                resolved["actual_game_date"]
            )
            resolved["audit_game_date"] = pd.to_datetime(resolved["audit_game_date"], errors="coerce")
            missing_date = resolved["audit_game_date"].isna()
            if missing_date.any():
                resolved.loc[missing_date, "audit_game_date"] = pd.to_datetime(
                    resolved.loc[missing_date, "resolved_at"], errors="coerce"
                ).dt.normalize()
            resolved["Data da rodada"] = resolved["audit_game_date"].dt.strftime("%Y-%m-%d")
            round_audit = (
                resolved.groupby("Data da rodada", dropna=False)
                .agg(
                    Jogadores=("player_id", "nunique"),
                    Previsoes=("id", "count"),
                    MAE_minutos=("minutes_error", "mean"),
                    MAE_pontos=("pts_error", "mean"),
                    MAE_rebotes=("reb_error", "mean"),
                    MAE_assistencias=("ast_error", "mean"),
                )
                .reset_index()
                .sort_values("Data da rodada", ascending=False)
            )
            st.dataframe(
                round_audit.style.format(
                    {
                        "MAE_minutos": "{:.1f}",
                        "MAE_pontos": "{:.1f}",
                        "MAE_rebotes": "{:.1f}",
                        "MAE_assistencias": "{:.1f}",
                    },
                    na_rep="—",
                ),
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Baixar auditoria das previsões (CSV)",
                data=resolved.sort_values("audit_game_date").to_csv(index=False).encode("utf-8-sig"),
                file_name="nba_player_prediction_audit.csv",
                mime="text/csv",
            )

        st.markdown("#### Todas as previsões")
        display_source = player_predictions.copy()
        if not resolved.empty:
            errors_for_display = resolved[
                ["id", "minutes_error", "pts_error", "reb_error", "ast_error"]
            ].drop_duplicates("id")
            display_source = display_source.merge(errors_for_display, on="id", how="left")
        display = display_source.rename(
            columns={
                "created_at": "Registrada em",
                "player_name": "Jogador",
                "opponent": "Adversário previsto",
                "target_game_date": "Data do jogo previsto",
                "actual_game_date": "Data do jogo real",
                "actual_opponent": "Adversário real",
                "actual_is_home": "Mando real",
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
                "minutes_error": "Erro abs. minutos",
                "pts_error": "Erro abs. pontos",
                "reb_error": "Erro abs. rebotes",
                "ast_error": "Erro abs. assistências",
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
                    "Erro abs. minutos": "{:.1f}",
                    "Erro abs. pontos": "{:.1f}",
                    "Erro abs. rebotes": "{:.1f}",
                    "Erro abs. assistências": "{:.1f}",
                },
                na_rep="—",
            ),
            hide_index=True,
            width="stretch",
        )
