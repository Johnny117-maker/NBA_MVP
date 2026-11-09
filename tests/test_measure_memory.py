import sqlite3

from scripts import measure_memory


def test_lista_de_paginas_inclui_home_e_todas_as_paginas_em_ordem():
    pages = measure_memory.pages()
    assert pages[0] == "app.py"
    assert "pages/16_Sistema.py" in pages
    numbers = [int(p.split("/")[1].split("_", 1)[0]) for p in pages[1:]]
    assert numbers == sorted(numbers)


def test_base_inexistente_ou_pequena_nao_conta_como_real(tmp_path):
    assert not measure_memory.has_real_data(tmp_path / "nao_existe.db")
    path = tmp_path / "nba.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE games (game_id TEXT)")
        connection.execute("CREATE TABLE player_game_stats (game_id TEXT)")
        connection.execute("INSERT INTO games VALUES ('1')")
    assert not measure_memory.has_real_data(path)


def test_arquivos_do_pacote_incluem_bancos_derivados(tmp_path):
    for name in ("nba.db", "nba_sync.sqlite", "nba_history.sqlite", "outro.txt"):
        (tmp_path / name).write_bytes(b"x" * 10)
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "a.parquet").write_bytes(b"y" * 5)
    files = measure_memory.database_files(tmp_path / "nba.db")
    assert {f.name for f in files} == {"nba.db", "nba_sync.sqlite", "nba_history.sqlite", "a.parquet"}
    assert measure_memory.total_bytes(files) == 35


def test_relatorio_avisa_quando_a_base_e_sintetica():
    results = [
        {"page": "app.py", "peak_mib": 100.0, "errors": []},
        {"page": "x.py", "peak_mib": None, "errors": ["falhou"]},
    ]
    text = measure_memory.format_report("sintética", [], 1048576, results)
    assert "NÃO representam" in text and "1.00 MiB" in text and "Maior pico: 100.0" in text
    assert "NÃO representam" not in measure_memory.format_report("real", [], 0, results)
