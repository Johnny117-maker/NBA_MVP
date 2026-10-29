from streamlit.testing.v1 import AppTest


def test_streamlit_app_loads_without_exceptions(app_db):
    app = AppTest.from_file("../app.py")
    app.run(timeout=30)
    assert not app.exception
    assert app.title or app.markdown


def test_home_prioritizes_today_without_loading_season_models(app_db, monkeypatch):
    def unnecessary(*args, **kwargs):
        raise AssertionError("A abertura não deve carregar o histórico completo.")

    monkeypatch.setattr("src.data.load_real_games", unnecessary)
    app = AppTest.from_file("../app.py").run(timeout=30)
    assert not app.exception
    assert any(metric.label == "Jogos hoje" for metric in app.metric)
    assert not app.toggle(key="home_season_details").value
