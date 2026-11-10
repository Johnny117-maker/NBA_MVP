import json
import sqlite3
import tarfile

import pytest
import requests
from streamlit.testing.v1 import AppTest

from scripts import build_serving_bundle, measure_memory
from src import cloud_bootstrap as cb
from src import deploy_mode, serving_bundle
from src.history_store import connect_history, history_root
from src.live_store import connect_state


class _Response:
    def __init__(self, body: bytes):
        self.status_code = 200
        self._body = body
        self.text = body.decode("utf-8", "replace")

    def iter_content(self, chunk_size=1):
        yield self._body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Release:
    """Release simulado a partir de uma pasta com os arquivos publicados."""

    def __init__(self, folder):
        self.folder = folder

    def get(self, url, **kwargs):
        path = self.folder / url.rsplit("/", 1)[-1]
        if not path.exists():
            raise requests.ConnectionError("sem arquivo")
        return _Response(path.read_bytes())

    def close(self):
        pass


@pytest.fixture
def source_with_history(_app_db_path, tmp_path):
    """Cópia do banco de teste com acervo (assets + 1 parquet de mentira) e estado operacional."""
    import shutil

    home = tmp_path / "origem"
    (home / "data").mkdir(parents=True)
    db = home / "data" / "nba.db"
    shutil.copy2(_app_db_path, db)
    root = history_root(db)
    (root / "x").mkdir(parents=True)
    (root / "x" / "a.parquet").write_bytes(b"parquet-de-mentira")
    with connect_history(db) as history:
        history.execute(
            "INSERT INTO assets (tag,name,year,source_url,relative_path) VALUES "
            "('t','a.parquet',2025,'u','x/a.parquet'),('t','b.parquet',2025,'u','x/ausente.parquet')"
        )
    with connect_state(db) as state:
        state.execute("INSERT INTO http_cache VALUES ('k','corpo',1.0)")
        state.execute("INSERT INTO api_usage VALUES ('p','2026-11',3)")
    return db


def _read_tables(path, sql):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_pacote_tem_manifesto_coerente_e_todos_os_bancos(source_with_history, tmp_path):
    out = tmp_path / "saida"
    manifest = serving_bundle.build_serving_bundle(source_with_history, out, version="v-teste")
    assert manifest["version"] == "v-teste"
    parsed = cb.BundleManifest.parse(json.loads((out / "manifest.json").read_text()))
    assert parsed.asset_sha256 == manifest["asset"]["sha256"]
    assert {"nba.db", "nba_sync.sqlite", "nba_analysis.sqlite", "nba_history.sqlite"} <= set(parsed.files)
    assert "history/x/a.parquet" in parsed.files
    with tarfile.open(out / parsed.asset_name) as bundle:
        assert not [m for m in bundle.getmembers() if m.name.endswith(("-wal", "-shm"))]


def test_origem_nao_e_alterada_e_operacionais_vao_vazios(source_with_history, tmp_path):
    before = source_with_history.read_bytes()
    out = tmp_path / "saida"
    serving_bundle.build_serving_bundle(source_with_history, out, version="v1")
    assert source_with_history.read_bytes() == before
    assert _read_tables(
        source_with_history.with_name("nba_sync.sqlite"), "SELECT COUNT(*) FROM http_cache"
    ) == [(1,)]
    extracted = tmp_path / "extraido"
    with tarfile.open(out / "nba-serving-v1.tar.gz") as bundle:
        bundle.extractall(extracted, filter="data")
    sync = extracted / "nba_sync.sqlite"
    assert _read_tables(sync, "SELECT COUNT(*) FROM http_cache") == [(0,)]
    assert _read_tables(sync, "SELECT COUNT(*) FROM api_usage") == [(0,)]


def test_sem_arquivos_de_historico_remove_os_assets_correspondentes(source_with_history, tmp_path):
    out = tmp_path / "saida"
    manifest = serving_bundle.build_serving_bundle(
        source_with_history, out, version="v1", include_history=False
    )
    assert not [f for f in manifest["files"] if f["name"].startswith("history/")]
    extracted = tmp_path / "extraido"
    with tarfile.open(out / "nba-serving-v1.tar.gz") as bundle:
        bundle.extractall(extracted, filter="data")
    assert _read_tables(extracted / "nba_history.sqlite", "SELECT COUNT(*) FROM assets") == [(0,)]


def test_asset_apontando_para_arquivo_ausente_e_descartado(source_with_history, tmp_path):
    serving_bundle.build_serving_bundle(source_with_history, tmp_path / "s", version="v1")
    extracted = tmp_path / "e"
    with tarfile.open(tmp_path / "s" / "nba-serving-v1.tar.gz") as bundle:
        bundle.extractall(extracted, filter="data")
    names = _read_tables(extracted / "nba_history.sqlite", "SELECT name FROM assets")
    assert names == [("a.parquet",)]


def test_corte_opcional_de_arremessos_por_temporada(source_with_history, tmp_path):
    total = _read_tables(source_with_history, "SELECT COUNT(*) FROM player_shots")[0][0]
    serving_bundle.build_serving_bundle(
        source_with_history, tmp_path / "s", version="v1", min_shot_season="9999-00"
    )
    extracted = tmp_path / "e"
    with tarfile.open(tmp_path / "s" / "nba-serving-v1.tar.gz") as bundle:
        bundle.extractall(extracted, filter="data")
    assert total > 0
    assert _read_tables(extracted / "nba.db", "SELECT COUNT(*) FROM player_shots") == [(0,)]


def test_por_padrao_nenhum_arremesso_e_cortado(source_with_history, tmp_path):
    total = _read_tables(source_with_history, "SELECT COUNT(*) FROM player_shots")[0][0]
    serving_bundle.build_serving_bundle(source_with_history, tmp_path / "s", version="v1")
    extracted = tmp_path / "e"
    with tarfile.open(tmp_path / "s" / "nba-serving-v1.tar.gz") as bundle:
        bundle.extractall(extracted, filter="data")
    assert _read_tables(extracted / "nba.db", "SELECT COUNT(*) FROM player_shots") == [(total,)]


def test_origem_inexistente_gera_erro_claro(tmp_path):
    with pytest.raises(serving_bundle.BundleBuildError):
        serving_bundle.build_serving_bundle(tmp_path / "nada.db", tmp_path / "s")
    with pytest.raises(serving_bundle.BundleBuildError):
        serving_bundle.pack_full_data(tmp_path / "nada.db", tmp_path / "f.tar.gz")


def test_relatorio_de_tamanho_usa_apenas_valores_medidos(source_with_history, tmp_path):
    manifest = serving_bundle.build_serving_bundle(source_with_history, tmp_path / "s", version="v1")
    report = serving_bundle.size_report(manifest)
    assert "dentro da meta" in report and "nba.db" in report
    big = {**manifest, "uncompressed_bytes": 400 * 1024 * 1024}
    assert "ACIMA da meta" in serving_bundle.size_report(big)


def test_script_gera_pacote_e_base_completa(source_with_history, tmp_path, capsys):
    out = tmp_path / "dist"
    code = build_serving_bundle.main(
        [
            "--db",
            str(source_with_history),
            "--output-dir",
            str(out),
            "--version",
            "v9",
            "--full-archive",
            str(out / "nba-full.tar.gz"),
        ]
    )
    assert code == 0
    assert (out / "nba-serving-v9.tar.gz").exists() and (out / "manifest.json").exists()
    assert (out / "nba-full.tar.gz.sha256").read_text().split()[0]
    with tarfile.open(out / "nba-full.tar.gz") as full:
        assert "nba.db" in full.getnames() and "history/x/a.parquet" in full.getnames()
    assert "Descompactado" in capsys.readouterr().out
    assert build_serving_bundle.main(["--db", str(tmp_path / "x.db"), "--output-dir", str(out)]) == 1


@pytest.fixture
def lean_bundle_home(source_with_history, tmp_path, monkeypatch):
    """Instala APENAS o pacote enxuto (via bootstrap simulado) em um NBA_DATA_HOME novo."""
    from src.ui import cloud

    out = tmp_path / "release"
    serving_bundle.build_serving_bundle(source_with_history, out, version="v1")
    home = tmp_path / "nuvem"
    status = cb.sync_bundle(_Release(out), home / "data", "https://exemplo.invalido/r")
    assert status.state == cb.STATE_UPDATED
    db = home / "data" / "nba.db"
    for name in ("NBA_DEPLOY_MODE", "NBA_AUTO_SYNC", "NBA_DATA_HOME"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    monkeypatch.setenv("NBA_AUTO_SYNC", "0")
    monkeypatch.setenv("NBA_DATA_HOME", str(home))
    monkeypatch.setattr("src.store.DEFAULT_DB_PATH", db)
    current = cb.BundleStatus(cb.STATE_CURRENT, "v1", "2026-11-09T12:00:00Z")
    monkeypatch.setattr(cb, "sync_bundle", lambda *a, **k: current)
    cloud._synchronized_status.clear()
    yield db
    cloud._synchronized_status.clear()
    deploy_mode.uninstall_read_only_guard()


@pytest.mark.parametrize("page", measure_memory.pages())
def test_todas_as_paginas_abrem_so_com_o_pacote_enxuto(lean_bundle_home, page):
    import hashlib

    folder = lean_bundle_home.parent

    def digests():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.*") if p.is_file()}

    before = digests()
    app = AppTest.from_file(f"../{page}").run(timeout=90)
    assert not app.exception, [str(e.value) for e in app.exception]
    assert digests() == before
