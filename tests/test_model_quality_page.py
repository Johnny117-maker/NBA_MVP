from streamlit.testing.v1 import AppTest


def test_model_quality_page_loads_without_exceptions(app_db):
    app = AppTest.from_file("../pages/6_Qualidade_Modelo.py")
    app.run(timeout=60)
    assert not app.exception


def test_model_quality_page_shows_all_three_model_types(app_db):
    app = AppTest.from_file("../pages/6_Qualidade_Modelo.py")
    app.run(timeout=60)
    assert not app.exception

    headings = " ".join(md.value for md in app.markdown)
    assert "Times" in headings
    assert "Jogadores" in headings
    assert "Zonas de arremesso" in headings
