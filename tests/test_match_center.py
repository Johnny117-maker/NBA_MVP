import pandas as pd
from streamlit.testing.v1 import AppTest

from src.live_types import EASTERN, LiveGame, current_season, utc_now


def test_match_center_keeps_all_views_accessible_without_training_models(app_db, monkeypatch):
    now = utc_now()
    day = now.astimezone(EASTERN).date().isoformat()
    game = LiveGame(
        "fixture",
        "fixture",
        day,
        current_season(),
        "BOS",
        "NYK",
        "pre",
        now.isoformat(),
        kickoff=(pd.Timestamp(now) + pd.Timedelta(2, unit="h")).isoformat(),
    )
    monkeypatch.setattr("src.live_store.read_live_games", lambda *args: [game])
    monkeypatch.setattr("src.ui.match_center._defense", lambda *args: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setattr("src.ui.match_center._assignments", lambda *args: pd.DataFrame())
    monkeypatch.setattr(
        "src.ui.match_center.injury_snapshot",
        lambda *args: (
            pd.DataFrame(
                [dict(player="Injured Player", team="BOS", status="Fora", injury="fixture", note="fixture")]
            ),
            dict(source="fixture", source_as_of=day),
        ),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("A central não deve treinar modelos na abertura.")

    monkeypatch.setattr("src.round_context._team_model_context", forbidden)
    app = AppTest.from_file("../app.py").run(timeout=30)
    app.switch_page("pages/15_Central_Partida.py").run(timeout=30)
    assert not app.exception
    for mode in ("Palpites", "Disponibilidade", "Defesa", "Ao vivo"):
        app.segmented_control(key="center_view").set_value(mode).run(timeout=30)
        assert not app.exception
        if mode == "Disponibilidade":
            assert any("Jogador" in frame.value.columns for frame in app.dataframe)
        if mode == "Defesa":
            assert any("registros publicados" in caption.value for caption in app.caption)


def test_center_handles_an_empty_schedule(app_db, monkeypatch):
    monkeypatch.setattr("src.live_store.read_live_games", lambda *args: [])
    app = AppTest.from_file("../app.py").run(timeout=30)
    app.switch_page("pages/15_Central_Partida.py").run(timeout=30)
    assert not app.exception
    assert any("Aguardando o calendário" in info.value for info in app.info)
