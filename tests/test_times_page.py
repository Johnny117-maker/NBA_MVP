from streamlit.testing.v1 import AppTest


def test_times_page_loads_without_exceptions(app_db):
    app = AppTest.from_file("../pages/0_Times.py")
    app.run(timeout=30)
    assert not app.exception
    assert app.title or app.markdown
