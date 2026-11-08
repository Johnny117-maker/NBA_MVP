import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.daily_games import today_et
from src.live_store import set_state
from src.live_types import EASTERN
from src.nba_schedule import SCHEDULE_COLUMNS


def _kickoff_within_nba_day(now: pd.Timestamp) -> pd.Timestamp:
    """Início posterior a `now`, sempre no mesmo dia NBA (fuso Eastern).

    "Agora + 3 horas" cruza a meia-noite da costa leste entre 21h e 24h ET, e a
    fotografia pré-jogo exige captura e início no mesmo dia NBA.
    """
    end_of_day = (now.tz_convert(EASTERN) + pd.Timedelta(1, unit="D")).normalize().tz_convert("UTC")
    return min(now + pd.Timedelta(3, unit="h"), now + (end_of_day - now) / 2)


@pytest.fixture(autouse=True)
def _offline_calendar(monkeypatch, tmp_path, app_db):
    st.cache_data.clear()
    st.cache_resource.clear()
    set_state(
        app_db,
        "injury_snapshot",
        {
            "source": "ESPN test",
            "source_updated": pd.Timestamp.now(tz="UTC").isoformat(),
            "source_as_of": today_et().isoformat(),
            "rows": [],
            "daily_snapshot": False,
        },
    )
    row = dict.fromkeys(SCHEDULE_COLUMNS)
    row.update(
        game_id="PICK1",
        game_date=pd.Timestamp(today_et()),
        game_datetime_utc=pd.Timestamp.now(tz="UTC") + pd.Timedelta(3, unit="h"),
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
    assert app.segmented_control(key="pick_view").value == "Jogadores"
    assert any("round-player" in block.value for block in app.markdown)
    assert any(button.label == "Gerar palpites de jogadores" for button in app.button)
    assert any("histórico" in warning.value.casefold() for warning in app.warning)


def test_saved_picks_are_ready_without_loading_or_training_other_models(app_db, monkeypatch, tmp_path):
    import sqlite3

    from src.analysis_archive import archive_snapshot
    from src.live_store import get_state
    from src.round_context import _form_table as load_form

    bulletin = get_state(app_db, "injury_snapshot", {})
    original, isolated = sqlite3.connect(app_db), sqlite3.connect(tmp_path / "nba.db")
    try:
        original.backup(isolated)
    finally:
        original.close()
        isolated.close()
    app_db = tmp_path / "nba.db"
    monkeypatch.setattr("src.store.DEFAULT_DB_PATH", app_db)
    set_state(app_db, "injury_snapshot", bulletin)
    day = today_et().isoformat()
    player = _first_pick(app_db)
    now = pd.Timestamp.now(tz="UTC")
    archive_snapshot(
        app_db,
        dict(
            game_key=f"{day}:NYK:BOS",
            day=day,
            state="pre",
            home="NYK",
            away="BOS",
            captured_at=now.isoformat(),
            kickoff=_kickoff_within_nba_day(now).isoformat(),
            history_end="2024-12-01",
            model={"train_end": "2024-12-01"},
            players=[
                dict(
                    player_id=int(player.player_id),
                    name=player.player_name,
                    team=player.team,
                    stats={stat: {"projected": 20.0} for stat in ("pts", "reb", "ast")},
                )
            ],
        ),
    )

    def unnecessary(*args, **kwargs):
        raise AssertionError("Projeções salvas não exigem recálculo.")

    monkeypatch.setattr("src.round_context._form_table", unnecessary)
    monkeypatch.setattr("src.round_context._team_model_context", unnecessary)
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    assert not app.exception
    assert any("Pontos" in frame.value.columns for frame in app.dataframe)
    assert not any(button.label == "Gerar palpites de jogadores" for button in app.button)
    _mark_injured(app_db, player)
    monkeypatch.setattr("src.round_context._form_table", load_form)
    app.run(timeout=30)
    assert not app.exception
    assert not any(frame.value.astype(str).eq(player.player_name).any().any() for frame in app.dataframe)
    assert not any(player.player_name in block.value for block in app.markdown)


def _first_pick(app_db):
    from src.nba_schedule import fetch_nba_schedule
    from src.round_context import _form_table
    from src.today_picks import round_highlights

    form = _form_table(str(app_db), app_db.stat().st_mtime, "historical-fallback", (), today_et())
    return round_highlights(form, fetch_nba_schedule(), top_n=1).iloc[0]


def _mark_injured(path, player):
    set_state(
        path,
        "injury_snapshot",
        {
            "source": "ESPN test",
            "source_updated": pd.Timestamp.now(tz="UTC").isoformat(),
            "rows": [{"player": player.player_name, "team": player.team, "status": "Fora"}],
        },
    )


def test_picks_remove_injured_from_preview_archive_and_projection_after_bulletin_change(app_db, monkeypatch):
    player = _first_pick(app_db)
    calls = []
    monkeypatch.setattr("src.round_context._project_player", lambda *args: calls.append(args[2]))
    monkeypatch.setattr(
        "src.ui.archive.read_snapshots",
        lambda *args: [
            {
                "captured_at": pd.Timestamp.now(tz="UTC").isoformat(),
                "away": "BOS",
                "home": "NYK",
                "players": [
                    {"name": player.player_name, "team": player.team, "stats": {"pts": {"projected": 30}}}
                ],
            }
        ],
    )
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    assert not app.exception
    assert any(player.player_name in block.value for block in app.markdown)
    _mark_injured(app_db, player)
    # Mantém os caches da forma e da sessão: só o boletim muda.
    app.run(timeout=30)
    assert not app.exception
    assert not any(player.player_name in block.value for block in app.markdown)
    next(button for button in app.button if button.label == "Gerar palpites de jogadores").click().run(
        timeout=30
    )
    assert not app.exception
    assert int(player.player_id) not in calls
    assert not any(player.player_name in block.value for block in app.markdown)
    set_state(
        app_db,
        "injury_snapshot",
        {
            "source": "ESPN test",
            "source_updated": pd.Timestamp.now(tz="UTC").isoformat(),
            "rows": [{"player": player.player_name, "team": player.team, "status": "Disponível"}],
        },
    )
    app.run(timeout=30)
    assert not app.exception
    assert any(player.player_name in block.value for block in app.markdown)


def test_picks_recheck_availability_changed_during_projection(app_db, monkeypatch):
    player = _first_pick(app_db)

    def projection(*args):
        if args[2] == int(player.player_id):
            _mark_injured(app_db, player)
        return None

    monkeypatch.setattr("src.round_context._project_player", projection)
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    next(button for button in app.button if button.label == "Gerar palpites de jogadores").click().run(
        timeout=30
    )
    assert not app.exception
    assert not any(player.player_name in block.value for block in app.markdown)


def test_missing_bulletin_suspends_only_individual_picks(app_db, monkeypatch):
    set_state(app_db, "injury_snapshot", {})
    monkeypatch.setattr("src.round_context._project_player", lambda *args: pytest.fail("Sem boletim válido"))
    app = AppTest.from_file("../pages/8_Palpites.py").run(timeout=30)
    assert not app.exception
    assert not any(button.label == "Gerar palpites de jogadores" for button in app.button)
    assert any("aguardam um boletim" in warning.value for warning in app.warning)
    app.segmented_control(key="pick_view").set_value("Confrontos").run(timeout=30)
    assert not app.exception
    assert any("Preferências do modelo" in block.value for block in app.markdown)


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
                "game_datetime_utc": pd.Timestamp.now(tz="UTC") - pd.Timedelta(2, unit="h"),
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
