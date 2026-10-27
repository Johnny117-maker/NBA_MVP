import pytest
from streamlit.testing.v1 import AppTest

from src.ui.navigation import PAGES


@pytest.mark.parametrize("page", PAGES, ids=[page.id for page in PAGES])
def test_all_pages_open_from_the_main_application(app_db, page):
    app = AppTest.from_file("../app.py").run(timeout=30)
    assert not app.exception
    if page.id != "overview":
        app.switch_page(page.path).run(timeout=60)
    assert not app.exception
    assert any("NBA ANALYTICS" in block.value for block in app.sidebar.markdown)
