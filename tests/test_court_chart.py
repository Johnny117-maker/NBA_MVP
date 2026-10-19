import math

import pandas as pd
import plotly.graph_objects as go

from src.court_chart import (
    _axial_round,
    _axial_to_pixel,
    _pixel_to_axial,
    _team_change_dates,
    add_court_shapes,
    court_shapes,
    hexbin_summary,
    shot_heatmap_chart,
    shot_hexbin_chart,
    shot_points_chart,
    zone_frequency_trend_chart,
)


def _shot(
    game_id="G1",
    game_date="2024-01-01",
    team_name="Boston Celtics",
    loc_x_ft=0.0,
    loc_y_ft=0.0,
    shot_distance=0.0,
    shot_type="2PT Field Goal",
    shot_zone_basic="Restricted Area",
    shot_made=True,
    game_event_id=1,
) -> dict:
    return {
        "player_id": 201,
        "player_name": "Jayson Tatum",
        "game_id": game_id,
        "game_event_id": game_event_id,
        "season": "2024-25",
        "game_date": pd.Timestamp(game_date),
        "team_id": 1,
        "team_name": team_name,
        "opponent": "New York Knicks",
        "period": 1,
        "minutes_remaining": 5,
        "seconds_remaining": 0,
        "event_type": "Made Shot" if shot_made else "Missed Shot",
        "action_type": "Jump Shot",
        "shot_type": shot_type,
        "shot_zone_basic": shot_zone_basic,
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "Less Than 8 ft.",
        "shot_distance": shot_distance,
        "loc_x": loc_x_ft * 10,
        "loc_y": loc_y_ft * 10,
        "loc_x_ft": loc_x_ft,
        "loc_y_ft": loc_y_ft,
        "shot_attempted": 1,
        "shot_made": shot_made,
        "source": "nba_api",
    }


# --- Geometria da quadra -----------------------------------------------------


def test_court_shapes_returns_shapes_with_expected_types():
    shapes = court_shapes()
    assert len(shapes) > 0
    assert {shape["type"] for shape in shapes} == {"circle", "line", "rect", "path"}


def test_court_shapes_hoop_is_centered_at_origin():
    shapes = court_shapes()
    hoop = shapes[0]
    assert hoop["type"] == "circle"
    assert hoop["x0"] < 0 < hoop["x1"]
    assert hoop["y0"] < 0 < hoop["y1"]


def test_add_court_shapes_sets_fixed_aspect_ratio():
    figure = add_court_shapes(go.Figure())
    assert figure.layout.yaxis.scaleanchor == "x"
    assert figure.layout.yaxis.scaleratio == 1


# --- Grade hexagonal ----------------------------------------------------------


def test_pixel_to_axial_and_back_round_trip_at_hex_centers():
    q, r = _pixel_to_axial(0.0, 0.0, 2.0)
    rounded_q, rounded_r = _axial_round(q, r)
    x, y = _axial_to_pixel(rounded_q, rounded_r, 2.0)
    assert math.isclose(x, 0.0, abs_tol=1e-9)
    assert math.isclose(y, 0.0, abs_tol=1e-9)


def test_hexbin_summary_groups_nearby_shots_into_the_same_bin():
    shots = pd.DataFrame(
        [
            _shot(loc_x_ft=0.0, loc_y_ft=0.0, shot_made=True, game_event_id=1),
            _shot(loc_x_ft=0.1, loc_y_ft=-0.1, shot_made=True, game_event_id=2),
            _shot(loc_x_ft=0.05, loc_y_ft=0.05, shot_made=False, game_event_id=3),
        ]
    )
    hexbins = hexbin_summary(shots, hex_size=2.0)
    assert len(hexbins) == 1
    assert hexbins.iloc[0]["attempts"] == 3
    assert hexbins.iloc[0]["makes"] == 2


def test_hexbin_summary_separates_far_apart_shots():
    shots = pd.DataFrame(
        [
            _shot(loc_x_ft=0.0, loc_y_ft=0.0, shot_made=True, game_event_id=1),
            _shot(loc_x_ft=20.0, loc_y_ft=20.0, shot_made=True, game_event_id=2),
        ]
    )
    hexbins = hexbin_summary(shots, hex_size=2.0)
    assert len(hexbins) == 2
    assert set(hexbins["attempts"]) == {1}


def test_hexbin_summary_empty_input_returns_empty_frame():
    hexbins = hexbin_summary(pd.DataFrame())
    assert hexbins.empty
    assert "points_per_shot" in hexbins.columns


# --- Marcação de troca de time --------------------------------------------


def test_team_change_dates_ignores_first_stint_and_detects_the_trade():
    shots = pd.DataFrame(
        [
            _shot(game_id="G1", game_date="2024-01-01", team_name="Boston Celtics", game_event_id=1),
            _shot(game_id="G2", game_date="2024-01-03", team_name="Boston Celtics", game_event_id=2),
            _shot(game_id="G3", game_date="2024-01-10", team_name="Miami Heat", game_event_id=3),
            _shot(game_id="G4", game_date="2024-01-12", team_name="Miami Heat", game_event_id=4),
        ]
    )
    changes = _team_change_dates(shots)
    assert changes == [pd.Timestamp("2024-01-10")]


def test_team_change_dates_empty_when_never_traded():
    shots = pd.DataFrame(
        [
            _shot(game_id="G1", game_date="2024-01-01", team_name="Boston Celtics", game_event_id=1),
            _shot(game_id="G2", game_date="2024-01-03", team_name="Boston Celtics", game_event_id=2),
        ]
    )
    assert _team_change_dates(shots) == []


# --- Smoke tests dos gráficos (não devem levantar exceção) --------------------


def test_charts_do_not_raise_with_data():
    shots = pd.DataFrame(
        [
            _shot(shot_made=True, game_event_id=1),
            _shot(loc_x_ft=25.0, loc_y_ft=2.0, shot_distance=25, shot_type="3PT Field Goal",
                  shot_zone_basic="Above the Break 3", shot_made=False, game_event_id=2),
        ]
    )
    for chart in (shot_points_chart, shot_heatmap_chart, shot_hexbin_chart, zone_frequency_trend_chart):
        figure = chart(shots)
        assert isinstance(figure, go.Figure)


def test_charts_do_not_raise_with_empty_data():
    empty = pd.DataFrame()
    for chart in (shot_points_chart, shot_heatmap_chart, shot_hexbin_chart, zone_frequency_trend_chart):
        figure = chart(empty)
        assert isinstance(figure, go.Figure)
