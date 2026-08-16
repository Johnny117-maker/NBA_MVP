from streamlit.testing.v1 import AppTest


def test_streamlit_app_loads_without_exceptions():
    app = AppTest.from_file("../app.py")
    app.run(timeout=30)
    assert not app.exception
    assert app.title or app.markdown
