import json

from scripts import update_injuries


def test_codigo_de_saida_reflete_se_o_boletim_foi_obtido(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        update_injuries, "refresh_injuries", lambda db, force: {"available": True, "errors": []}
    )
    assert update_injuries.main(["--db", str(tmp_path / "nba.db")]) == 0
    assert json.loads(capsys.readouterr().out)["available"] is True
    monkeypatch.setattr(
        update_injuries,
        "refresh_injuries",
        lambda db, force: {"available": False, "errors": ["ESPN: ProviderError"]},
    )
    assert update_injuries.main(["--db", str(tmp_path / "nba.db")]) == 1
