import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.daily_games import today_et
from src.nba_schedule import SCHEDULE_COLUMNS


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    # O calendário fica em st.cache_data: sem limpar, um teste herda o resultado do outro.
    st.cache_data.clear()
    st.cache_resource.clear()
    yield


def _schedule_for_today() -> pd.DataFrame:
    row = {column: None for column in SCHEDULE_COLUMNS}
    row.update(
        game_id="TEST1",
        game_date=pd.Timestamp(today_et()),
        game_datetime_utc=pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=3),
        game_status=1,
        game_status_text="Scheduled",
        home_team_tricode="NYK",
        home_team_name="New York Knicks",
        away_team_tricode="BOS",
        away_team_name="Boston Celtics",
        arena_name="Madison Square Garden",
        schedule_source="NBA oficial",
    )
    return pd.DataFrame([row], columns=SCHEDULE_COLUMNS)


def test_daily_games_page_lists_the_days_games(app_db, monkeypatch):
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())

    app = AppTest.from_file("../pages/7_Jogos_do_Dia.py")
    app.run(timeout=90)
    assert not app.exception

    text = " ".join(md.value for md in app.markdown)
    assert "Boston Celtics @ New York Knicks" in text


def test_daily_games_page_shows_message_when_there_are_no_games(app_db, monkeypatch):
    monkeypatch.setattr(
        "src.nba_schedule.fetch_nba_schedule",
        lambda **kwargs: pd.DataFrame(columns=SCHEDULE_COLUMNS),
    )

    app = AppTest.from_file("../pages/7_Jogos_do_Dia.py")
    app.run(timeout=90)
    assert not app.exception
    assert any("Nenhum jogo encontrado" in info.value for info in app.info)