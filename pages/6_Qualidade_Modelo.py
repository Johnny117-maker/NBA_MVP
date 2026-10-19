from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.shot_features import ZONE_LABELS_PT
from src.store import DEFAULT_DB_PATH, read_model_training_log
from src.ui import components, states, theme
from src.ui.formatters import format_datetime_br, format_int_br

MODEL_LABELS = {"team": "Times", "player": "Jogadores", "zone": "Zonas de arremesso"}

st.set_page_config(
    page_title="Qualidade do Modelo — NBA Analytics Lab",
    page_icon="📊",
    layout="wide",
)

theme.inject_base_style()

st.markdown("## 📊 Qualidade do Modelo")
st.caption(
    "Erros, calibração e histórico de retreinamento dos três modelos do projeto "
    "(times, jogadores e zonas de arremesso) — separado de qual time, jogador ou "
    "adversário está selecionado nas páginas de análise."
)

training_log = read_model_training_log(DEFAULT_DB_PATH)


def _render_team_metrics(latest: pd.Series) -> None:
    metrics = latest["metrics"]
    components.metric_row(
        [
            {"label": "Accuracy", "value": f"{metrics['accuracy']:.1%}"},
            {"label": "Log Loss", "value": f"{metrics['log_loss']:.3f}"},
            {"label": "Brier Score", "value": f"{metrics['brier_score']:.3f}"},
            {"label": "MAE casa", "value": f"{metrics['home_points_mae']:.1f} pts"},
            {"label": "MAE visitante", "value": f"{metrics['away_points_mae']:.1f} pts"},
        ]
    )
    st.caption(
        "Avaliação nos 20% finais da base em ordem cronológica. Treinado em "
        f"{format_datetime_br(latest['trained_at'])} com {format_int_br(int(latest['n_games']))} jogos."
    )


def _render_player_metrics(latest: pd.Series) -> None:
    metrics = latest["metrics"]
    items = [
        {"label": "MAE minutos", "value": f"{metrics['minutes_mae']:.1f}"},
        {"label": "MAE pontos", "value": f"{metrics['pts_mae']:.1f}"},
        {"label": "MAE rebotes", "value": f"{metrics['reb_mae']:.1f}"},
        {"label": "MAE assistências", "value": f"{metrics['ast_mae']:.1f}"},
    ]
    if "pts_chain_mae" in metrics:
        items.append(
            {
                "label": "MAE cadeia FGA × TS%",
                "value": f"{metrics['pts_chain_mae']:.1f}",
            }
        )
    if "pts_baseline_mae" in metrics:
        items.append(
            {
                "label": "MAE referência recente",
                "value": f"{metrics['pts_baseline_mae']:.1f}",
            }
        )
    if "pts_interval_coverage" in metrics:
        items.append(
            {
                "label": "Cobertura do intervalo (pts)",
                "value": f"{metrics['pts_interval_coverage']:.0%}",
            }
        )
    components.metric_row(items)
    st.caption(
        f"Validação walk-forward por datas completas ({metrics.get('n_folds', '—')} folds), treinado em "
        f"{format_datetime_br(latest['trained_at'])} com {format_int_br(int(latest['n_games']))} linhas. "
        "Pontos avaliam apenas partidas em que o atleta registrou minutos. "
        "As referências comparam o modelo direto com a cadeia FGA × TS% e com a taxa recente × minutos previstos."
    )


def _render_zone_metrics(latest: pd.Series) -> None:
    metrics = latest["metrics"]
    components.metric_row(
        [{"label": "MAE de pontos de bola-de-quadra", "value": f"{metrics['fg_points_mae']:.2f}"}]
    )

    zone_rows = [
        {
            "Zona": ZONE_LABELS_PT.get(
                key.removeprefix("share_mae_"), key.removeprefix("share_mae_")
            ),
            "MAE de participação": value,
        }
        for key, value in metrics.items()
        if key.startswith("share_mae_")
    ]
    if zone_rows:
        with st.expander("MAE de participação por zona"):
            st.dataframe(
                pd.DataFrame(zone_rows).style.format({"MAE de participação": "{:.1%}"}),
                hide_index=True,
                use_container_width=True,
            )

    st.caption(
        f"Validação walk-forward ({metrics.get('n_folds', '—')} folds), treinado em "
        f"{format_datetime_br(latest['trained_at'])} com {format_int_br(int(latest['n_games']))} jogos. "
        "O MAE de pontos usa o FGA real de cada jogo do teste (não uma previsão), para isolar o "
        "erro da distribuição/eficiência por zona do erro do modelo de volume de arremessos."
    )


_RENDER_BY_MODEL_TYPE = {
    "team": _render_team_metrics,
    "player": _render_player_metrics,
    "zone": _render_zone_metrics,
}


tab_current, tab_history = st.tabs(["Métricas atuais", "Histórico de treinamento"])

with tab_current:
    if training_log.empty:
        states.empty_state(
            "Nenhum retreinamento registrado ainda",
            "Rode o script de retreinamento para gerar as primeiras métricas.",
            actions=[
                ("Retreinar", "rode 'python scripts/retrain_models.py' no terminal do projeto")
            ],
        )
    else:
        for model_type, label in MODEL_LABELS.items():
            subset = training_log[training_log["model_type"] == model_type]
            st.markdown(f"#### {label}")
            if subset.empty:
                st.info(f"Nenhum treinamento de '{label.lower()}' registrado ainda.")
            else:
                _RENDER_BY_MODEL_TYPE[model_type](subset.iloc[0])
            st.divider()

with tab_history:
    if training_log.empty:
        st.info(
            "Nenhum retreinamento registrado ainda. Rode "
            "'python scripts/retrain_models.py' no terminal do projeto."
        )
    else:
        for model_type, label in MODEL_LABELS.items():
            subset = training_log[training_log["model_type"] == model_type].sort_values("trained_at")
            if subset.empty:
                continue

            st.markdown(f"#### {label}")
            metrics_df = pd.json_normalize(subset["metrics"]).set_index(subset.index)
            metrics_df["trained_at"] = subset["trained_at"]
            metrics_df["n_games"] = subset["n_games"]

            st.dataframe(metrics_df, hide_index=True, use_container_width=True)

            metric_columns = [
                column
                for column in metrics_df.columns
                if column not in ("trained_at", "n_games") and not column.startswith("share_mae_")
            ]
            if len(subset) > 1 and metric_columns:
                figure = px.line(
                    metrics_df,
                    x="trained_at",
                    y=metric_columns,
                    markers=True,
                )
                figure.update_layout(
                    height=320,
                    xaxis_title=None,
                    yaxis_title=None,
                    legend_title=None,
                    margin=dict(l=10, r=10, t=20, b=10),
                )
                st.plotly_chart(figure, use_container_width=True)
