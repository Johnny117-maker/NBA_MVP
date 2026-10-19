import pytest
from streamlit.testing.v1 import AppTest

from src.ui.components import note, persistent_selectbox


def test_note_rejects_invalid_kind():
    with pytest.raises(ValueError):
        note("texto", kind="bogus")


def test_ui_components_render_without_exceptions():
    app = AppTest.from_file("_ui_harness_page.py")
    app.run(timeout=30)
    assert not app.exception

    assert any("NBA API" in md.value for md in app.markdown)
    assert any("Atualizado em 16/08/2026" in md.value for md in app.markdown)
    assert any("Nota informativa de teste" in md.value for md in app.markdown)

    assert len(app.metric) == 7
    assert any(m.label == "Jogos" and m.value == "1.230" for m in app.metric)

    assert any("Exibindo 18 de 74" in c.value and "moderada" in c.value for c in app.caption)

    assert any("Apenas 4 jogos" in w.value for w in app.warning)
    assert any("atualizados há 9 dias" in w.value for w in app.warning)

    assert any("Falha ao atualizar" in e.value for e in app.error)


def test_clear_filters_button_resets_widget_to_default():
    app = AppTest.from_file("_ui_harness_page.py")
    app.run(timeout=30)
    assert not app.exception

    text_input = next(t for t in app.text_input if t.key == "algum_filtro")
    text_input.set_value("valor alterado").run(timeout=30)
    assert any("Valor atual: valor alterado" in md.value for md in app.markdown)

    button = next(b for b in app.button if b.label == "Limpar filtros")
    button.click().run(timeout=30)
    assert not app.exception

    text_input_after = next(t for t in app.text_input if t.key == "algum_filtro")
    assert text_input_after.value == "valor inicial"


def test_empty_state_stops_execution_and_shows_actions():
    app = AppTest.from_file("_ui_harness_page.py")
    app.run(timeout=30)
    assert not app.exception

    checkbox = next(c for c in app.checkbox if c.key == "show_empty")
    checkbox.set_value(True).run(timeout=30)
    assert not app.exception

    assert any("Nenhum dado ainda" in info.value for info in app.info)
    assert any("Carregar demo" in c.value for c in app.caption)
    assert not any("NÃO deveria aparecer" in md.value for md in app.markdown)


def test_persistent_selectbox_rejects_empty_options():
    with pytest.raises(ValueError):
        persistent_selectbox("rótulo", [], query_key="x")


def test_persistent_selectbox_writes_default_choice_to_query_params():
    app = AppTest.from_file("_ui_harness_page.py")
    app.run(timeout=30)
    assert not app.exception

    # Streamlit st.query_params retorna uma string quando há um único valor.
    assert app.query_params["jogador_teste"] == "Ana"
    assert any("Selecionado: Ana" in md.value for md in app.markdown)


def test_persistent_selectbox_restores_value_from_query_params():
    app = AppTest.from_file("_ui_harness_page.py")
    app.query_params["jogador_teste"] = "Carla"
    app.run(timeout=30)
    assert not app.exception

    select = next(s for s in app.selectbox if s.label == "Jogador de teste")
    assert select.value == "Carla"
    assert any("Selecionado: Carla" in md.value for md in app.markdown)


def test_persistent_selectbox_falls_back_when_query_param_is_invalid():
    app = AppTest.from_file("_ui_harness_page.py")
    app.query_params["jogador_teste"] = "Não Existe"
    app.run(timeout=30)
    assert not app.exception

    select = next(s for s in app.selectbox if s.label == "Jogador de teste")
    assert select.value == "Ana"


def test_persistent_selectbox_updates_query_params_when_changed():
    app = AppTest.from_file("_ui_harness_page.py")
    app.run(timeout=30)
    assert not app.exception

    select = next(s for s in app.selectbox if s.label == "Jogador de teste")
    select.set_value("Beto").run(timeout=30)
    assert not app.exception

    # Não usar lista: st.query_params usa o formato QueryParams atual do Streamlit.
    assert app.query_params["jogador_teste"] == "Beto"
    assert any("Selecionado: Beto" in md.value for md in app.markdown)
