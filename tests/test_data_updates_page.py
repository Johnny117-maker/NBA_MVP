from streamlit.testing.v1 import AppTest


def test_data_updates_page_loads_without_exceptions(app_db):
    app = AppTest.from_file("../pages/5_Dados_Atualizacoes.py")
    app.run(timeout=30)
    assert not app.exception


def test_data_updates_page_shows_pending_shots_summary(app_db):
    app = AppTest.from_file("../pages/5_Dados_Atualizacoes.py")
    app.run(timeout=30)
    assert not app.exception

    shots_tab_text = " ".join(md.value for md in app.markdown)
    assert "pares jogador-temporada" in shots_tab_text or "Nenhum jogador pendente" in " ".join(
        s.value for s in app.success
    )


def test_invalid_season_is_rejected_before_querying_the_api(app_db, monkeypatch):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("Não deve consultar a API com uma temporada inválida.")

    monkeypatch.setattr("src.nba_client.fetch_season_games", unexpected_request)
    app = AppTest.from_file("../pages/5_Dados_Atualizacoes.py").run(timeout=30)
    app.text_input[0].set_value("2026-20")
    next(button for button in app.button if button.label == "Coletar esta temporada").click().run(timeout=30)
    assert not app.exception
    assert any("temporada válida" in error.value for error in app.error)
