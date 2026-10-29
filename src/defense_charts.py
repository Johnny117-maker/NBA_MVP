"""Mapa da localização dos arremessos cedidos; não é mapa de posicionamento dos defensores."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .court_chart import add_court_shapes


def defense_court_chart(cells: pd.DataFrame, *, metric: str = "fg_pct", minimum: int = 5) -> go.Figure:
    if metric not in {"fg_pct", "attempts"} or minimum < 1:
        raise ValueError("Parâmetros do mapa inválidos.")
    figure = go.Figure()
    if not cells.empty:
        rows = cells.loc[cells.attempts.ge(minimum)]
        percent = metric == "fg_pct"
        figure.add_trace(
            go.Scatter(
                x=rows.x,
                y=rows.y,
                mode="markers",
                customdata=rows[["attempts", "makes", "fg_pct"]],
                marker=dict(
                    symbol="square",
                    size=np.clip(7 + np.sqrt(rows.attempts) * 2, 10, 28),
                    color=rows[metric] * (100 if percent else 1),
                    colorscale="RdBu_r" if percent else "Viridis",
                    cmin=0,
                    cmax=100 if percent else None,
                    opacity=0.85,
                    colorbar=dict(title="FG% cedido" if percent else "Tentativas"),
                ),
                hovertemplate="%{customdata[0]:.0f} tentativas · %{customdata[1]:.0f} acertos"
                "<br>FG% cedido: %{customdata[2]:.1%}<extra></extra>",
            )
        )
    add_court_shapes(figure)
    figure.update_layout(height=530, margin=dict(l=5, r=5, t=5, b=5), showlegend=False)
    return figure
