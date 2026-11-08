from datetime import timedelta

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


@pytest.fixture(autouse=True)
def _offline_roster(monkeypatch):
    monkeypatch.setattr("src.current_roster.fetch_current_roster", lambda: pd.DataFrame())


@pytest.fixture(autouse=True)
def _isolated_schedule_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "schedule.json"
    monkeypatch.setattr("src.schedule_storage.DEFAULT_SCHEDULE_CACHE_PATH", cache_path)
    return cache_path


def _schedule_for_today() -> pd.DataFrame:
    row = {column: None for column in SCHEDULE_COLUMNS}
    row.update(
        game_id="TEST1",
        game_date=pd.Timestamp(today_et()),
        game_datetime_utc=pd.Timestamp.now(tz="UTC") + pd.Timedelta(3, unit="h"),
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

    app = AppTest.from_file("../pages/7_Jogos.py")
    app.run(timeout=90)
    assert not app.exception

    text = " ".join(md.value for md in app.markdown)
    assert "Boston Celtics @ New York Knicks" in text


def test_players_are_the_initial_tab_and_have_profile_links(app_db, monkeypatch):
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert app.tabs[0].label == "Jogadores de destaque"
    cards = [block.value for block in app.markdown if 'class="round-player"' in block.value]
    assert cards
    assert all("Último jogo:" in card and "player_id=" in card for card in cards)


def test_highlight_search_treats_regex_characters_as_literal(app_db, monkeypatch):
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    next(widget for widget in app.text_input if widget.label == "Buscar jogador de destaque").set_value("[")
    app.run(timeout=30)
    assert not app.exception
    assert any("Nenhum destaque corresponde" in info.value for info in app.info)


def test_daily_games_page_calls_the_production_schedule_client(app_db, monkeypatch):
    # Substitui apenas o HTTP: preserva a assinatura e a chamada reais do cliente.
    # Um mock permissivo de fetch_nba_schedule(**kwargs) esconderia incompatibilidades.
    payload = {
        "leagueSchedule": {"gameDates": [{
            "gameDate": today_et().isoformat(),
            "games": [{
                "gameId": "INTEGRATION1",
                "gameStatus": 1,
                "gameDateTimeUTC": f"{today_et().isoformat()}T23:30:00Z",
                "homeTeam": {"teamTricode": "NYK"},
                "awayTeam": {"teamTricode": "BOS"},
            }],
        }]},
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr("src.nba_schedule.requests.get", lambda *args, **kwargs: Response())
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)


def test_public_schedule_renders_without_requesting_blocked_roster_api(app_db, monkeypatch):
    from src.public_schedule import PUBLIC_SCHEDULE_SOURCE

    schedule = _schedule_for_today()
    schedule["schedule_source"] = PUBLIC_SCHEDULE_SOURCE

    def blocked_roster():
        raise AssertionError("Não deve chamar a API NBA quando o calendário usa o arquivo alternativo.")

    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: schedule)
    monkeypatch.setattr("src.current_roster.fetch_current_roster", blocked_roster)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)
    assert any("atualização periódica" in caption.value for caption in app.caption)
    assert not any("elenco atual da NBA" in warning.value for warning in app.warning)


def test_daily_games_page_shows_message_when_there_are_no_games(app_db, monkeypatch):
    monkeypatch.setattr(
        "src.nba_schedule.fetch_nba_schedule",
        lambda **kwargs: pd.DataFrame(columns=SCHEDULE_COLUMNS),
    )

    app = AppTest.from_file("../pages/7_Jogos.py")
    app.run(timeout=90)
    assert not app.exception
    assert any("Nenhum jogo encontrado" in info.value for info in app.info)


def test_team_probabilities_work_without_player_data_and_ignore_future_games(app_db, monkeypatch):
    from src.data import generate_demo_games, team_snapshot
    from src.model import predict_game, train_models

    history = generate_demo_games(number_of_games=100)
    yesterday = pd.Timestamp(today_et()) - pd.Timedelta(1, unit="D")
    history["game_date"] = pd.date_range(end=yesterday, periods=100)
    future = pd.concat([history.tail(1), history.tail(1)], ignore_index=True)
    future["game_date"] = pd.date_range(start=pd.Timestamp(today_et()), periods=2)
    combined = pd.concat([history, future], ignore_index=True)
    schedule = _schedule_for_today()
    home, away = history.iloc[-1][["home_team", "away_team"]]
    schedule["home_team_name"] = home
    schedule["away_team_name"] = away
    trained = []

    def capture_training(games):
        trained.append(games.copy())
        return train_models(games)

    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: schedule)
    monkeypatch.setattr("src.store.count_player_games", lambda *args: 0)
    monkeypatch.setattr("src.data.load_real_games", lambda *args: combined)
    monkeypatch.setattr("src.model.train_models", capture_training)

    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert len(trained) == 1
    pd.testing.assert_frame_equal(trained[0], history)

    from src.daily_games import team_rest_days

    expected = predict_game(
        train_models(history), team_snapshot(history, home), team_snapshot(history, away),
        team_rest_days(history, home, today_et()), team_rest_days(history, away, today_et()),
    )
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics[f"Prob. {home}"] == f"{expected.home_win_probability:.0%}"
    assert metrics[f"Prob. {away}"] == f"{expected.away_win_probability:.0%}"


def test_insufficient_team_history_keeps_schedule_visible(app_db, monkeypatch):
    from src.data import load_real_games

    history = load_real_games(app_db).head(10)
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())
    monkeypatch.setattr("src.data.load_real_games", lambda *args: history)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)
    assert any("Probabilidades indisponíveis" in info.value for info in app.info)


def test_roster_failure_keeps_highlights_available(app_db, monkeypatch):
    def unavailable():
        raise RuntimeError("Fonte indisponível")

    monkeypatch.setattr("src.current_roster.fetch_current_roster", unavailable)
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("Não foi possível consultar o elenco" in warning.value for warning in app.warning)
    highlights = [table for table in app.dataframe if "Jogador" in table.value.columns]
    assert len(highlights) == 2


def test_highlights_exclude_results_from_the_selected_day(app_db, monkeypatch):
    from src.player_data import load_player_games

    history = load_player_games(source="real", db_path=app_db)
    future = history.head(1).copy()
    future["player_id"] = 999999
    future["player_name"] = "Resultado futuro"
    future["team"] = "BOS"
    future["game_date"] = pd.Timestamp(today_et())
    future["pts"] = 100
    combined = pd.concat([history, future], ignore_index=True)
    monkeypatch.setattr("src.player_data.load_player_games", lambda **kwargs: combined)
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())

    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert len([frame for frame in app.dataframe if "Jogador" in frame.value.columns]) == 2
    assert all(
        "Resultado futuro" not in frame.value["Jogador"].tolist()
        for frame in app.dataframe if "Jogador" in frame.value.columns
    )


def test_past_dates_do_not_consult_current_roster(app_db, monkeypatch):
    yesterday = today_et() - timedelta(days=1)
    schedule = _schedule_for_today()
    schedule["game_date"] = pd.Timestamp(yesterday)
    calls = []

    def current_roster():
        calls.append(True)
        return pd.DataFrame()

    monkeypatch.setattr("src.current_roster.fetch_current_roster", current_roster)
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: schedule)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    app.date_input[0].set_value(yesterday).run(timeout=30)
    assert not app.exception
    assert not calls
    assert len([frame for frame in app.dataframe if "Jogador" in frame.value.columns]) == 2


def test_player_projection_can_be_enabled(app_db, monkeypatch):
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    app.checkbox[0].check().run(timeout=60)
    assert not app.exception
    assert len([frame for frame in app.dataframe if "Jogador" in frame.value.columns]) == 2
    for frame in [frame for frame in app.dataframe if "Jogador" in frame.value.columns]:
        assert {"Proj. PTS", "Proj. REB", "Proj. AST", "Confiança"}.issubset(frame.value.columns)
        assert frame.value["Proj. PTS"].notna().all()


def _unavailable_schedule(**kwargs):
    raise RuntimeError("Conexão interrompida pelas fontes NBA/ESPN")


def test_network_failure_uses_saved_calendar(app_db, monkeypatch, _isolated_schedule_cache):
    from src.schedule_storage import save_schedule_cache

    save_schedule_cache(_schedule_for_today(), _isolated_schedule_cache)
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", _unavailable_schedule)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)
    assert any("salva anteriormente" in info.value for info in app.info)
    assert any("salvo localmente" in md.value for md in app.markdown)


def test_network_failure_allows_manual_game_and_keeps_it_on_rerun(app_db, monkeypatch):
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", _unavailable_schedule)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("NBA e ESPN não responderam" in warning.value for warning in app.warning)
    app.selectbox[0].select("NYK")
    app.selectbox[1].select("BOS")
    next(button for button in app.button if button.label == "Analisar confronto").click().run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)
    assert any("Cadastro manual" in md.value for md in app.markdown)
    assert len([frame for frame in app.dataframe if "Jogador" in frame.value.columns]) == 2
    app.slider[0].set_value(2).run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)


def test_manual_game_requires_two_different_teams(app_db, monkeypatch):
    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", _unavailable_schedule)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    app.selectbox[0].select("BOS")
    app.selectbox[1].select("BOS")
    next(button for button in app.button if button.label == "Analisar confronto").click().run(timeout=30)
    assert not app.exception
    assert any("dois times diferentes" in error.value for error in app.error)
    assert not app.dataframe


def test_network_errors_are_not_cached(app_db, monkeypatch):
    calls = []

    def unavailable(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("Fonte indisponível")

    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", unavailable)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    app.run(timeout=30)
    assert not app.exception
    assert len(calls) == 2
    assert all(call["start_date"] == today_et() and call["lookahead_days"] == 1 for call in calls)


def test_cache_write_failure_does_not_hide_live_games(app_db, monkeypatch):
    def denied(*args):
        raise PermissionError("Somente leitura")

    monkeypatch.setattr("src.nba_schedule.fetch_nba_schedule", lambda **kwargs: _schedule_for_today())
    monkeypatch.setattr("src.schedule_storage.save_schedule_cache", denied)
    app = AppTest.from_file("../pages/7_Jogos.py").run(timeout=30)
    assert not app.exception
    assert any("Boston Celtics @ New York Knicks" in md.value for md in app.markdown)
