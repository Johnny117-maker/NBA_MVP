from streamlit.testing.v1 import AppTest


def test_data_updates_page_loads_without_exceptions():
    app = AppTest.from_file("../pages/5_Dados_Atualizacoes.py")
    app.run(timeout=30)
    assert not app.exception


def test_data_updates_page_shows_pending_shots_summary():
    app = AppTest.from_file("../pages/5_Dados_Atualizacoes.py")
    app.run(timeout=30)
    assert not app.exception

    shots_tab_text = " ".join(md.value for md in app.markdown)
    assert "pares jogador-temporada" in shots_tab_text or "Nenhum jogador pendente" in " ".join(
        s.value for s in app.success
    )
