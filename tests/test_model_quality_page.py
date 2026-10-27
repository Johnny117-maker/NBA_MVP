from streamlit.testing.v1 import AppTest

from src.store import log_model_training, read_model_training_log


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


def test_quality_identifies_new_score_model_only_for_versioned_training(app_db):
    metrics = read_model_training_log(app_db).query("model_type == 'team'").iloc[0]["metrics"]
    log_model_training("team", 60, {**metrics, "score_model_version": 2.0}, app_db)
    app = AppTest.from_file("../pages/6_Qualidade_Modelo.py").run(timeout=60)
    assert not app.exception
    assert any("Placar v2" in caption.value for caption in app.caption)
