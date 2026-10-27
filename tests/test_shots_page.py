from streamlit.testing.v1 import AppTest


def test_shots_page_loads_without_exceptions(app_db):
    app = AppTest.from_file("../pages/4_Mapa_Arremessos.py")
    app.run(timeout=60)
    assert not app.exception


def test_shots_page_switching_player_does_not_raise(app_db):
    app = AppTest.from_file("../pages/4_Mapa_Arremessos.py")
    app.run(timeout=60)
    assert not app.exception

    player_select = next(s for s in app.selectbox if s.label == "Jogador")
    options = player_select.options
    if len(options) > 1:
        player_select.set_value(options[1]).run(timeout=60)
        assert not app.exception


def test_shots_page_comparison_modes_do_not_raise(app_db):
    # Cada modo troca de ramo condicional e cria widgets diferentes (ex.: os
    # seletores de temporada só existem no modo "Duas temporadas") — uma
    # instância nova de `AppTest` por modo evita que o driver de teste tente
    # reconciliar o estado de um widget que não existe mais na árvore atual
    # (peculiaridade do `AppTest`, não afeta um usuário real no navegador).
    comparison_mode = next(
        r
        for r in AppTest.from_file("../pages/4_Mapa_Arremessos.py").run(timeout=60).radio
        if r.label == "O que comparar?"
    )
    for option in comparison_mode.options:
        app = AppTest.from_file("../pages/4_Mapa_Arremessos.py")
        app.run(timeout=60)
        assert not app.exception

        mode = next(r for r in app.radio if r.label == "O que comparar?")
        mode.set_value(option).run(timeout=60)
        assert not app.exception


def test_shots_page_zone_projection_updates_without_raising(app_db):
    app = AppTest.from_file("../pages/4_Mapa_Arremessos.py")
    app.run(timeout=60)
    assert not app.exception
    next(b for b in app.button if b.label == "Carregar projeções por zona").click().run(timeout=60)
    assert not app.exception

    opponent_select = next(s for s in app.selectbox if s.label == "Próximo adversário")
    if len(opponent_select.options) > 1:
        opponent_select.set_value(opponent_select.options[1]).run(timeout=60)
        assert not app.exception

    fga_input = next(n for n in app.number_input if n.label == "Arremessos de quadra previstos (FGA)")
    fga_input.set_value(15.0).run(timeout=60)
    assert not app.exception
    assert any(m.label == "Pontos de bola-de-quadra esperados" for m in app.metric)
