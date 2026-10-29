from datetime import UTC, datetime

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.live_providers import ApiKeys
from src.live_types import LiveGame, LivePlayer


def _version_watch_app(path: str):
    import streamlit as st

    from src.sync_runtime import watch_history_version

    st.session_state["executions"] = st.session_state.get("executions", 0) + 1
    watch_history_version(path)
    st.metric("Execuções", st.session_state["executions"])


def test_new_history_reruns_the_whole_page_once_but_monitor_ticks_do_not(tmp_path):
    path = tmp_path / "history.db"
    app = AppTest.from_function(_version_watch_app, args=(str(path),)).run(timeout=15)
    assert app.metric[0].value == "1"
    path.write_bytes(b"new history")
    app.run(timeout=15)
    assert not app.exception
    assert app.metric[0].value == "3"  # Tentativa inicial + rerun integral solicitado pelo fragmento.
    (tmp_path / "history_sync.sqlite").write_bytes(b"clock tick")
    app.run(timeout=15)
    assert app.metric[0].value == "4"


def test_opportunity_screen_and_live_line_calculator_use_current_observations(app_db, monkeypatch):
    now = datetime(2026, 10, 28, 22, tzinfo=UTC)
    player = LivePlayer("1", "Live Test Player", "BOS", 22, {"pts": 15, "reb": 5, "ast": 3}, canonical_id=1)
    game = LiveGame(
        "0022600050",
        "NBA",
        "2026-10-28",
        "2026-27",
        "BOS",
        "NYK",
        "live",
        now.isoformat(),
        70,
        68,
        3,
        6,
        boxscore_at=now.isoformat(),
        players=[player],
    )
    history = pd.DataFrame(
        {
            "player_id": [1] * 6,
            "player_name": [player.name] * 6,
            "team": ["BOS"] * 6,
            "game_date": pd.date_range("2026-10-16", periods=6, freq="2D"),
            "season": ["2026-27"] * 6,
            "minutes": [32] * 6,
            "pts": [22, 24, 20, 25, 22, 23],
            "reb": [5, 6, 7, 6, 5, 7],
            "ast": [3, 4, 3, 4, 5, 4],
        }
    )
    monkeypatch.setattr("src.ui.live.current_games", lambda path: [game])
    monkeypatch.setattr("src.ui.live._history", lambda path, version: history)
    monkeypatch.setattr("src.ui.live.utc_now", lambda: now)
    monkeypatch.setattr("src.prop_model.utc_now", lambda: now)
    monkeypatch.setattr("src.ui.live.load_api_keys", lambda: ApiKeys())
    app = AppTest.from_file("../app.py").run(timeout=45)
    assert not app.exception
    app.toggle(key="home_live_opportunities").set_value(True).run(timeout=45)
    assert not app.exception
    assert any("Oportunidades da rodada" in heading.value for heading in app.subheader)
    app.switch_page("pages/9_Oportunidades.py").run(timeout=45)
    assert not app.exception
    app.get_by_key("all_props_mode").set_value("Jogos ao vivo").run(timeout=30)
    assert not app.exception
    assert any("BOS" in heading.value and "70" in heading.value for heading in app.subheader)
    app.get_by_key("all_props_mode").set_value("Analisar linha").run(timeout=30)
    assert not app.exception
    assert any(metric.label == "Over" for metric in app.metric)
    assert any(button.label == "Consultar linhas das casas" and button.disabled for button in app.button)
