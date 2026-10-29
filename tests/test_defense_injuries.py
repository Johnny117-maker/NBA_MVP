from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.defense_analytics import court_cells, defense_index
from src.defense_charts import defense_court_chart
from src.history_store import connect_history
from src.injuries import injury_snapshot, parse_archive_injuries, parse_espn_injuries, refresh_injuries
from src.live_providers import ProviderError
from src.live_store import set_state
from src.player_matchups import MATCHUP_COLUMNS, defender_opponents


def test_index_direction_ties_missing_data_and_minimum_sample():
    frame = pd.DataFrame(
        dict(
            team=["A", "B", "C", "D"],
            games=[10, 10, 10, 1],
            drtg=[100, 120, 90, 80],
            paint_allowed_100=[30, 50, np.nan, 20],
            paint_games=[10, 10, 10, 1],
            opp_3p_pct=[0.3, 0.4, 0.2, 0.2],
            dreb_pct=[0.8, 0.6, 0.9, 0.9],
        )
    )
    result = defense_index(frame)
    assert result.defense_index.iloc[0] == 100
    assert result.defense_index.iloc[1] == 0
    assert result.defense_index.iloc[2:].isna().all()
    tied = frame.iloc[:2].copy()
    tied.loc[:, "drtg"] = 100
    assert defense_index(tied, {"drtg": 1}).defense_index.eq(50).all()
    frame.loc[0, "paint_games"] = 9
    assert defense_index(frame).defense_index.isna().all()
    with pytest.raises(ValueError):
        defense_index(frame, {"drtg": -1})


def test_map_cells_ignore_missing_coordinates_and_preserve_makes_and_attempts():
    shots = pd.DataFrame(dict(x_ft=[0, 0.2, np.nan, 99], y_ft=[0, 0.1, 1, 0], made=[1, 0, 1, 1]))
    cells = court_cells(shots)
    assert cells.attempts.sum() == 2
    assert cells.makes.sum() == 1
    assert cells.fg_pct.iloc[0] == 0.5
    visible = defense_court_chart(cells, minimum=2)
    hidden = defense_court_chart(cells, minimum=3)
    assert len(visible.data[0].x) == 1
    assert len(hidden.data[0].x) == 0


def matchup(off, defender, made, attempted, *, phase="Temporada regular", game="g1"):
    row = dict.fromkeys(MATCHUP_COLUMNS, 0)
    row.update(
        game_id=game,
        game_date="2025-01-01",
        season="2024-25",
        phase=phase,
        off_id=off,
        off_name=f"Atacante {off}",
        off_team="BOS",
        def_id=defender,
        def_name=f"Marcador {defender}",
        def_team="NYK",
        def_position="G",
        seconds=30,
        possessions=10,
        points=made * 2,
        fgm=made,
        fga=attempted,
        source="fixture",
    )
    return tuple(row[key] for key in MATCHUP_COLUMNS)


def save_matchups(path):
    with connect_history(path) as connection:
        connection.executemany(
            "INSERT INTO player_matchups VALUES (" + ",".join("?" for _ in MATCHUP_COLUMNS) + ")",
            [
                matchup(1, 10, 1, 5),
                matchup(1, 11, 15, 30),
                matchup(2, 10, 1, 1),
                matchup(2, 11, 2, 10),
                matchup(1, 12, 100, 100, phase="Playoffs"),
            ],
        )


def test_defender_reference_excludes_himself_and_other_phases_and_marks_small_samples(tmp_path):
    path = tmp_path / "nba.db"
    save_matchups(path)
    rows, summary = defender_opponents(path, "2024-25", "Temporada regular", 10)
    assert set(rows.def_id) == {10}
    first = summary.loc[summary.off_id.eq(1)].iloc[0]
    assert first.reference_pct == 0.5
    assert first.difference_pp == pytest.approx(-30)
    assert summary.loc[summary.off_id.eq(2), "reference_pct"].isna().all()
    assert summary.loc[summary.off_id.eq(2), "difference_pp"].isna().all()


def espn_payload(status="Out"):
    return {
        "injuries": [
            {
                "displayName": "Boston Celtics",
                "injuries": [
                    {
                        "athlete": {
                            "id": "100",
                            "displayName": "Atleta Teste",
                            "position": {"abbreviation": "G"},
                        },
                        "status": status,
                        "date": "2025-01-01T12:00Z",
                        "details": {"type": "Ankle"},
                    }
                ],
            }
        ]
    }


def test_espn_schema_identity_unknown_status_and_empty_confirmed_bulletin():
    frame = parse_espn_injuries(espn_payload("Unknown designation"))
    assert frame.iloc[0].team == "BOS"
    assert frame.iloc[0].athlete_id == "100"
    assert frame.iloc[0].status == "Não classificado"
    assert frame.iloc[0].estimated_return == ""
    assert parse_espn_injuries({"injuries": []}).empty
    with pytest.raises(ValueError):
        parse_espn_injuries({"changed": []})


def test_archive_uses_last_complete_snapshot_not_last_entry_per_player():
    frame = pd.DataFrame(
        [
            dict(
                as_of_date="2025-01-01",
                athlete_id=100,
                athlete_display_name="Recuperado",
                team_display_name="Boston Celtics",
                status="Out",
            ),
            dict(
                as_of_date="2025-01-02",
                athlete_id=200,
                athlete_display_name="Atual",
                team_display_name="Boston Celtics",
                status="Day-To-Day",
            ),
        ]
    )
    result, as_of = parse_archive_injuries(frame)
    assert as_of == "2025-01-02"
    assert result.player.tolist() == ["Atual"]
    assert result.status.tolist() == ["Dia a dia"]


class Client:
    def __init__(self, payload=None):
        self.payload = payload
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.payload is None:
            raise ProviderError("Fonte indisponível")
        return self.payload


def test_failure_keeps_snapshot_and_poll_throttle_survives_repeated_clicks(tmp_path, monkeypatch):
    path = tmp_path / "nba.db"
    now = datetime(2025, 1, 1, tzinfo=UTC)
    monkeypatch.setattr("src.injuries.utc_now", lambda: now)
    success = Client(espn_payload())
    assert refresh_injuries(path, client=success)["available"]
    before, state = injury_snapshot(path)
    assert not state["stale"]
    refresh_injuries(path, force=True, client=success)
    assert success.calls == 1
    now += timedelta(minutes=20)
    failed = refresh_injuries(path, client=Client())
    after, state = injury_snapshot(path)
    pd.testing.assert_frame_equal(before, after)
    assert not failed["available"]
    assert state["stale"]
    now += timedelta(minutes=10)
    refresh_injuries(path, client=Client({"injuries": []}))
    assert injury_snapshot(path)[0].empty


def test_injury_page_filters_snapshot_without_network(app_db):
    set_state(
        app_db,
        "injury_snapshot",
        dict(
            rows=parse_espn_injuries(espn_payload()).to_dict("records"),
            source="ESPN",
            source_as_of="2025-01-01",
            source_updated="2025-01-01T00:00:00Z",
            daily_snapshot=False,
        ),
    )
    app = AppTest.from_file("../app.py").run(timeout=60)
    app.switch_page("pages/14_Lesoes.py").run(timeout=60)
    assert not app.exception
    assert any(
        "Atleta Teste" in frame.value.get("player", pd.Series(dtype=str)).tolist() for frame in app.dataframe
    )
    app.text_input(key="injury_search").set_value("Inexistente").run(timeout=60)
    assert not app.exception
    assert any("Nenhum registro" in item.value for item in app.info)


def test_marker_mode_opens_from_main_application(app_db):
    save_matchups(app_db)
    app = AppTest.from_file("../app.py").run(timeout=60)
    app.switch_page("pages/13_Marcacoes.py").run(timeout=60)
    next(widget for widget in app.selectbox if widget.label == "Analisar").set_value("Marcador")
    app.run(timeout=60)
    assert not app.exception
    assert any("Marcador" == widget.label for widget in app.selectbox)
