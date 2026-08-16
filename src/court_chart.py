from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .shot_features import MIDRANGE_ZONES, THREE_POINT_ZONES, add_shot_value

# Dimensões da quadra em pés, cesta na origem (0, 0) — mesmo sistema de
# coordenadas de `loc_x_ft`/`loc_y_ft` (src/shot_connector.py). Valores
# seguem a geometria oficial da NBA, no mesmo espírito das referências
# públicas usadas para desenhar quadras a partir do ShotChartDetail.
HOOP_RADIUS = 0.75
BACKBOARD_HALF_WIDTH = 3.0
BACKBOARD_Y = -0.75
PAINT_OUTER_HALF_WIDTH = 8.0
PAINT_INNER_HALF_WIDTH = 6.0
PAINT_Y_TOP = 14.25
BASELINE_Y = -4.75
FREE_THROW_CIRCLE_RADIUS = 6.0
RESTRICTED_AREA_RADIUS = 4.0
THREE_POINT_CORNER_X = 22.0
THREE_POINT_CORNER_Y_TOP = 9.25
THREE_POINT_ARC_RADIUS = 23.75
COURT_HALF_WIDTH = 25.0
HALF_COURT_Y = 41.75
CENTER_CIRCLE_RADIUS = 6.0
CENTER_CIRCLE_INNER_RADIUS = 2.0


def _arc_path(
    center_x: float, center_y: float, radius: float, start_deg: float, end_deg: float, steps: int = 60
) -> str:
    """Aproxima um arco por uma polilinha (SVG path `M ... L ...`), ângulos em graus
    medidos a partir do eixo x positivo, sentido anti-horário."""
    angles = np.radians(np.linspace(start_deg, end_deg, steps))
    xs = center_x + radius * np.cos(angles)
    ys = center_y + radius * np.sin(angles)
    points = " L ".join(f"{x:.3f},{y:.3f}" for x, y in zip(xs, ys))
    return f"M {points}"


def court_shapes(line_color: str = "#94a3b8", line_width: float = 1.5) -> list[dict]:
    """Formas (shapes) do plotly para desenhar a meia quadra defensiva/ofensiva.

    Cesta na origem; eixo y cresce em direção ao meio de quadra. Usada tanto
    pelo mapa de pontos quanto pelos mapas de calor/hexagonal (seção 3 do
    planejamento).
    """
    common = dict(line=dict(color=line_color, width=line_width), fillcolor="rgba(0,0,0,0)")

    three_arc_start = math.degrees(math.atan2(THREE_POINT_CORNER_Y_TOP, THREE_POINT_CORNER_X))
    three_arc_end = 180 - three_arc_start

    return [
        dict(type="circle", x0=-HOOP_RADIUS, y0=-HOOP_RADIUS, x1=HOOP_RADIUS, y1=HOOP_RADIUS, **common),
        dict(
            type="line",
            x0=-BACKBOARD_HALF_WIDTH,
            y0=BACKBOARD_Y,
            x1=BACKBOARD_HALF_WIDTH,
            y1=BACKBOARD_Y,
            **common,
        ),
        dict(
            type="rect",
            x0=-PAINT_OUTER_HALF_WIDTH,
            y0=BASELINE_Y,
            x1=PAINT_OUTER_HALF_WIDTH,
            y1=PAINT_Y_TOP,
            **common,
        ),
        dict(
            type="rect",
            x0=-PAINT_INNER_HALF_WIDTH,
            y0=BASELINE_Y,
            x1=PAINT_INNER_HALF_WIDTH,
            y1=PAINT_Y_TOP,
            **common,
        ),
        dict(
            type="circle",
            x0=-FREE_THROW_CIRCLE_RADIUS,
            y0=PAINT_Y_TOP - FREE_THROW_CIRCLE_RADIUS,
            x1=FREE_THROW_CIRCLE_RADIUS,
            y1=PAINT_Y_TOP + FREE_THROW_CIRCLE_RADIUS,
            **common,
        ),
        dict(
            type="path",
            path=_arc_path(0, 0, RESTRICTED_AREA_RADIUS, 0, 180),
            **common,
        ),
        dict(
            type="line",
            x0=-THREE_POINT_CORNER_X,
            y0=BASELINE_Y,
            x1=-THREE_POINT_CORNER_X,
            y1=THREE_POINT_CORNER_Y_TOP,
            **common,
        ),
        dict(
            type="line",
            x0=THREE_POINT_CORNER_X,
            y0=BASELINE_Y,
            x1=THREE_POINT_CORNER_X,
            y1=THREE_POINT_CORNER_Y_TOP,
            **common,
        ),
        dict(
            type="path",
            path=_arc_path(0, 0, THREE_POINT_ARC_RADIUS, three_arc_start, three_arc_end),
            **common,
        ),
        dict(
            type="line",
            x0=-COURT_HALF_WIDTH,
            y0=HALF_COURT_Y,
            x1=COURT_HALF_WIDTH,
            y1=HALF_COURT_Y,
            **common,
        ),
        dict(
            type="circle",
            x0=-CENTER_CIRCLE_RADIUS,
            y0=HALF_COURT_Y - CENTER_CIRCLE_RADIUS,
            x1=CENTER_CIRCLE_RADIUS,
            y1=HALF_COURT_Y + CENTER_CIRCLE_RADIUS,
            **common,
        ),
        dict(
            type="circle",
            x0=-CENTER_CIRCLE_INNER_RADIUS,
            y0=HALF_COURT_Y - CENTER_CIRCLE_INNER_RADIUS,
            x1=CENTER_CIRCLE_INNER_RADIUS,
            y1=HALF_COURT_Y + CENTER_CIRCLE_INNER_RADIUS,
            **common,
        ),
    ]


def add_court_shapes(figure: go.Figure, line_color: str = "#94a3b8") -> go.Figure:
    """Adiciona a quadra ao `figure` e fixa proporção/eixos (meia quadra ofensiva)."""
    for shape in court_shapes(line_color=line_color):
        figure.add_shape(**shape)
    figure.update_xaxes(range=[-27, 27], visible=False, fixedrange=True)
    figure.update_yaxes(
        range=[BASELINE_Y - 2, HALF_COURT_Y + 4],
        visible=False,
        scaleanchor="x",
        scaleratio=1,
        fixedrange=True,
    )
    figure.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return figure


def _shot_hover_text(shots: pd.DataFrame) -> list[str]:
    return [
        f"{row.game_date:%d/%m/%Y} vs {row.opponent}<br>"
        f"{row.action_type} — {row.shot_zone_basic} ({row.shot_distance:.0f} pés)"
        for row in shots.itertuples()
    ]


def shot_points_chart(shots: pd.DataFrame) -> go.Figure:
    """Mapa de pontos: cada tentativa na posição em que ocorreu (seção 3.1)."""
    figure = go.Figure()
    if not shots.empty:
        made = shots[shots["shot_made"].astype(bool)]
        missed = shots[~shots["shot_made"].astype(bool)]
        figure.add_trace(
            go.Scatter(
                x=missed["loc_x_ft"],
                y=missed["loc_y_ft"],
                mode="markers",
                name="Errou",
                marker=dict(color="#f87171", size=7, opacity=0.55, symbol="x-thin", line=dict(width=1)),
                text=_shot_hover_text(missed),
                hoverinfo="text",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=made["loc_x_ft"],
                y=made["loc_y_ft"],
                mode="markers",
                name="Converteu",
                marker=dict(color="#4ade80", size=7, opacity=0.65),
                text=_shot_hover_text(made),
                hoverinfo="text",
            )
        )
    add_court_shapes(figure)
    figure.update_layout(
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return figure


def shot_heatmap_chart(shots: pd.DataFrame, bin_size: float = 1.5) -> go.Figure:
    """Mapa de calor de volume (não eficiência): concentração de tentativas (seção 3.2).

    Usa um histograma 2D discreto (`Histogram2d`), não um contorno suavizado:
    `Histogram2dContour` interpola entre bins distantes e, com arremessos
    concentrados em clusters separados (ex.: perto da cesta e na linha de
    três), pode "conectar" os clusters com uma mancha onde não há dado
    nenhum — enganoso para um mapa que deveria mostrar só volume real.
    """
    figure = go.Figure()
    if not shots.empty:
        figure.add_trace(
            go.Histogram2d(
                x=shots["loc_x_ft"],
                y=shots["loc_y_ft"],
                xbins=dict(size=bin_size),
                ybins=dict(size=bin_size),
                colorscale=[
                    [0.0, "rgba(15,23,42,0)"],
                    [0.25, "#1d4ed8"],
                    [0.55, "#38bdf8"],
                    [0.8, "#f97316"],
                    [1.0, "#facc15"],
                ],
                zsmooth=False,
                showscale=False,
                opacity=0.85,
            )
        )
    add_court_shapes(figure, line_color="#f8fafc")
    figure.update_layout(height=420, margin=dict(l=10, r=10, t=20, b=10))
    return figure


def _pixel_to_axial(x: np.ndarray, y: np.ndarray, size: float) -> tuple[np.ndarray, np.ndarray]:
    """Converte coordenadas (pés) em coordenadas axiais de hexágono "pointy-top".

    Fórmula padrão de grade hexagonal (Red Blob Games, algoritmo público de
    referência para hex grids).
    """
    q = (math.sqrt(3) / 3 * x - 1 / 3 * y) / size
    r = (2 / 3 * y) / size
    return q, r


def _axial_round(q: np.ndarray, r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Arredonda coordenadas axiais fracionárias para o hexágono mais próximo."""
    cube_x, cube_z = q, r
    cube_y = -cube_x - cube_z

    round_x, round_y, round_z = np.round(cube_x), np.round(cube_y), np.round(cube_z)
    diff_x = np.abs(round_x - cube_x)
    diff_y = np.abs(round_y - cube_y)
    diff_z = np.abs(round_z - cube_z)

    fix_x = (diff_x > diff_y) & (diff_x > diff_z)
    fix_z = ~fix_x & (diff_y > diff_z)

    round_x = np.where(fix_x, -round_y - round_z, round_x)
    round_z = np.where(fix_z, -round_x - round_y, round_z)
    return round_x, round_z


def _axial_to_pixel(q: np.ndarray, r: np.ndarray, size: float) -> tuple[np.ndarray, np.ndarray]:
    x = size * (math.sqrt(3) * q + math.sqrt(3) / 2 * r)
    y = size * (3 / 2 * r)
    return x, y


HEXBIN_COLUMNS = ["hex_q", "hex_r", "center_x", "center_y", "attempts", "makes", "points", "fg_pct", "points_per_shot"]


def hexbin_summary(shots: pd.DataFrame, hex_size: float = 2.0) -> pd.DataFrame:
    """Agrupa arremessos numa grade hexagonal (seção 3.3 do planejamento).

    `hex_size` (pés) controla a resolução: hexágonos menores mostram mais
    detalhe espacial, mas com menos tentativas por hexágono — mais ruído.
    """
    if shots.empty:
        return pd.DataFrame(columns=HEXBIN_COLUMNS)

    data = add_shot_value(shots)
    made = data["shot_made"].astype(bool)
    data["points"] = np.where(made, data["shot_value"], 0)

    q, r = _pixel_to_axial(data["loc_x_ft"].to_numpy(dtype=float), data["loc_y_ft"].to_numpy(dtype=float), hex_size)
    hex_q, hex_r = _axial_round(q, r)
    data = data.assign(hex_q=hex_q, hex_r=hex_r)

    grouped = data.groupby(["hex_q", "hex_r"], as_index=False).agg(
        attempts=("shot_attempted", "size"),
        makes=("shot_made", "sum"),
        points=("points", "sum"),
    )
    grouped["makes"] = grouped["makes"].astype(int)
    grouped["fg_pct"] = grouped["makes"] / grouped["attempts"]
    grouped["points_per_shot"] = grouped["points"] / grouped["attempts"]

    center_x, center_y = _axial_to_pixel(
        grouped["hex_q"].to_numpy(dtype=float), grouped["hex_r"].to_numpy(dtype=float), hex_size
    )
    grouped["center_x"] = center_x
    grouped["center_y"] = center_y
    return grouped[HEXBIN_COLUMNS]


def shot_hexbin_chart(
    shots: pd.DataFrame,
    league_average_points_per_shot: float | None = None,
    hex_size: float = 2.0,
) -> go.Figure:
    """Mapa hexagonal: tamanho = volume de tentativas, cor = pontos por tentativa (seção 3.3).

    Quando `league_average_points_per_shot` é informado, a escala de cor fica
    centrada nele (`RdYlBu_r`): azul é abaixo da liga, vermelho é acima.
    """
    hexbins = hexbin_summary(shots, hex_size=hex_size)
    figure = go.Figure()
    if not hexbins.empty:
        max_attempts = float(hexbins["attempts"].max())
        sizes = 10 + 26 * np.sqrt(hexbins["attempts"] / max_attempts)
        marker: dict[str, object] = dict(
            symbol="hexagon",
            size=sizes,
            color=hexbins["points_per_shot"],
            colorscale="RdYlBu_r",
            colorbar=dict(title="Pontos<br>/tentativa"),
            line=dict(width=1, color="#0f172a"),
        )
        if league_average_points_per_shot is not None:
            marker["cmid"] = league_average_points_per_shot

        figure.add_trace(
            go.Scatter(
                x=hexbins["center_x"],
                y=hexbins["center_y"],
                mode="markers",
                marker=marker,
                text=[
                    f"{int(row.attempts)} tentativas, {row.fg_pct:.1%} de aproveitamento, "
                    f"{row.points_per_shot:.2f} pontos/tentativa"
                    for row in hexbins.itertuples()
                ],
                hoverinfo="text",
                showlegend=False,
            )
        )
    add_court_shapes(figure, line_color="#475569")
    figure.update_layout(height=440, margin=dict(l=10, r=10, t=20, b=10))
    return figure


def _team_change_dates(shots: pd.DataFrame) -> list[pd.Timestamp]:
    """Datas de troca de time, uma linha por jogo (mesmo princípio de
    `assign_team_stints`, aplicado aqui a `player_shots.team_name`).

    A primeira passagem não conta como troca — é só o começo do histórico.
    """
    games = (
        shots[["game_id", "game_date", "team_name"]]
        .drop_duplicates()
        .sort_values("game_date")
        .reset_index(drop=True)
    )
    if games.empty:
        return []
    changed = games["team_name"] != games["team_name"].shift(1)
    changed.iloc[0] = False
    return games.loc[changed, "game_date"].tolist()


def zone_frequency_trend_chart(shots: pd.DataFrame, window: int = 10) -> go.Figure:
    """Frequência de arremessos por categoria de zona ao longo da temporada.

    Média móvel de `window` jogos, com linhas tracejadas marcando troca de
    time — responde "como uma mudança de time alterou seus arremessos?"
    (seção 1 do planejamento) sem precisar de nenhuma coleta nova.
    """
    figure = go.Figure()
    if shots.empty:
        figure.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10))
        return figure

    per_game = (
        shots.assign(
            is_rim=lambda d: d["shot_zone_basic"] == "Restricted Area",
            is_three=lambda d: d["shot_zone_basic"].isin(THREE_POINT_ZONES),
            is_midrange=lambda d: d["shot_zone_basic"].isin(MIDRANGE_ZONES),
        )
        .groupby(["game_id", "game_date"], as_index=False)[["is_rim", "is_three", "is_midrange"]]
        .mean()
        .sort_values("game_date")
    )
    per_game["Aro"] = per_game["is_rim"].rolling(window, min_periods=1).mean()
    per_game["Três"] = per_game["is_three"].rolling(window, min_periods=1).mean()
    per_game["Meia distância"] = per_game["is_midrange"].rolling(window, min_periods=1).mean()

    for column, color in (("Aro", "#4ade80"), ("Três", "#38bdf8"), ("Meia distância", "#f97316")):
        figure.add_trace(
            go.Scatter(
                x=per_game["game_date"],
                y=per_game[column],
                mode="lines",
                name=column,
                line=dict(color=color),
            )
        )
    for trade_date in _team_change_dates(shots):
        figure.add_vline(x=trade_date.timestamp() * 1000, line_dash="dash", line_color="#93a1ac")

    figure.update_layout(
        height=320,
        yaxis_tickformat=".0%",
        yaxis_title=f"Frequência (média móvel de {window} jogos)",
        xaxis_title=None,
        legend_title=None,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    return figure
