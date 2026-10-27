import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.daily_games import today_et
from src.nba_schedule import SCHEDULE_COLUMNS


@pytest.fixture(autouse=True)
def _offline_calendar(monkeypatch, tmp_path):
    st.cache_data.clear()
    st.cache_resource.clear()
    row = dict.fromkeys(SCHEDULE_COLUMNS)
    row.update(
        game_id="PICK1",
        game_date=pd.Timestamp(today_et()),
        game_datetime_utc=pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=3),
        game_status=1,
        home_team_tricode="NYK",
        home_team_name="New York Knicks",
        away_team_tricode="BOS",
        away_team_name="Boston Celtics",
        schedule_source="SportsDataverse test",
    )
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: pd.DataFrame([row]))
    monkeypatch.setattr("src.schedule_storage.DEFAULT_SCHEDULE_CACHE_PATH", tmp_path / "calendar.json")


def test_picks_show_today_and_player_preview_without_training_player_models(app_db, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("O treino de jogadores exige uma ação explícita.")

    monkeypatch.setattr("src.round_context.train_player_models", unexpected)
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    assert not app.exception
    assert app.tabs[0].label == "Palpites de jogadores"
    assert any("round-player" in block.value for block in app.markdown)
    assert any(button.label == "Gerar palpites de jogadores" for button in app.button)
    assert any("histórico" in warning.value.casefold() for warning in app.warning)


def test_picks_generate_player_projections_after_request(app_db):
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    next(button for button in app.button if button.label == "Gerar palpites de jogadores").click().run(
        timeout=60
    )
    assert not app.exception
    assert any(metric.label == "Pontos" for metric in app.metric)
    assert any("Último jogo:" in caption.value for caption in app.caption)


def test_memory_failure_preserves_a_usable_page(app_db, monkeypatch):
    def memory_failure(*args):
        raise MemoryError("Simulação de memória insuficiente")

    monkeypatch.setattr("src.round_context._project_player", memory_failure)
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    generate = next(button for button in app.button if button.label == "Gerar palpites de jogadores")
    generate.click().run(timeout=30)
    assert not app.exception
    assert any("Memória insuficiente" in error.value for error in app.error)
    app.run(timeout=30)
    assert not app.exception
    assert any("round-player" in block.value for block in app.markdown)


def test_no_new_picks_for_live_or_completed_games(app_db, monkeypatch):
    schedule = pd.DataFrame(
        [
            {
                "game_id": "ended",
                "game_date": pd.Timestamp(today_et()),
                "game_status": 3,
                "game_datetime_utc": pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=2),
            }
        ]
    ).reindex(columns=SCHEDULE_COLUMNS)
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: schedule)
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    assert not app.exception
    assert any("Nenhum jogo de hoje" in info.value for info in app.info)
    assert not any(button.label == "Gerar palpites de jogadores" for button in app.button)


def test_player_profile_deep_link_selects_the_requested_athlete(app_db):
    from src.player_data import load_player_games

    athlete = load_player_games(source="real", db_path=app_db).iloc[-1]
    app = AppTest.from_file("../pages/1_Jogadores.py")
    app.query_params["view"] = "profile"
    app.query_params["player_id"] = str(athlete["player_id"])
    app.run(timeout=30)
    assert not app.exception
    assert app.tabs[0].label == "Perfil individual"
    selected = next(widget for widget in app.selectbox if widget.key == "profile_player_select_real")
    assert athlete["player_name"] in selected.value


def test_daily_games_and_picks_reuse_the_same_calendar(app_db, monkeypatch):
    from src import nba_schedule

    fetch = nba_schedule.fetch_nba_schedule
    calls = []

    def capture(**kwargs):
        calls.append(kwargs)
        return fetch(**kwargs)

    monkeypatch.setattr(nba_schedule, "fetch_nba_schedule", capture)
    app = AppTest.from_file("../app.py").run(timeout=30)
    app.switch_page("pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    app.switch_page("pages/8_Palpites.py").run(timeout=30)
    assert not app.exception
    assert len(calls) == 1
