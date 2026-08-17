from streamlit.testing.v1 import AppTest


def test_players_page_loads_without_exceptions(app_db):
    app = AppTest.from_file("../pages/1_Jogadores.py")
    app.run(timeout=90)
    assert not app.exception


def test_profile_tab_filters_do_not_raise_and_narrow_the_game_count(app_db):
    app = AppTest.from_file("../pages/1_Jogadores.py")
    app.run(timeout=90)
    assert not app.exception

    profile_tab = app.tabs[1]
    games_before = int(next(m for m in profile_tab.get("metric") if m.label == "Jogos").value)

    home_away = next(s for s in profile_tab.get("selectbox") if s.label == "Casa/Fora")
    home_away.set_value("Casa").run(timeout=90)
    assert not app.exception

    profile_tab = app.tabs[1]
    games_after = int(next(m for m in profile_tab.get("metric") if m.label == "Jogos").value)
    assert games_after <= games_before


def test_profile_tab_shows_a_warning_when_filters_match_no_games(app_db):
    app = AppTest.from_file("../pages/1_Jogadores.py")
    app.run(timeout=90)
    assert not app.exception

    profile_tab = app.tabs[1]
    min_minutes = next(n for n in profile_tab.get("number_input") if n.label == "Minutos mínimos")
    min_minutes.set_value(48).run(timeout=90)
    assert not app.exception

    warnings = [w.value for w in app.tabs[1].get("warning")]
    assert any("Nenhum jogo encontrado" in message for message in warnings)
