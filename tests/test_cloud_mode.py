import hashlib
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from src import deploy_mode
from src.app_paths import state_root
from src.remote_archive import archive_token


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _clean_guard():
    yield
    deploy_mode.uninstall_read_only_guard()


def test_sem_a_variavel_o_app_continua_no_modo_local(monkeypatch):
    monkeypatch.delenv("NBA_DEPLOY_MODE", raising=False)
    monkeypatch.delenv("NBA_DATA_HOME", raising=False)
    monkeypatch.setattr(deploy_mode, "_secret_value", lambda name: "")
    original = sqlite3.connect
    assert not deploy_mode.is_cloud()
    assert deploy_mode.apply_cloud_environment() is False
    assert sqlite3.connect is original
    assert state_root() != deploy_mode.Path(deploy_mode.CLOUD_DEFAULT_DATA_HOME)


@pytest.mark.parametrize("value", ["cloud", " CLOUD "])
def test_modo_nuvem_pelo_ambiente(monkeypatch, value):
    monkeypatch.setenv("NBA_DEPLOY_MODE", value)
    assert deploy_mode.is_cloud()


def test_modo_nuvem_pelos_secrets(monkeypatch):
    monkeypatch.delenv("NBA_DEPLOY_MODE", raising=False)
    monkeypatch.setattr(deploy_mode, "_secret_value", lambda name: "cloud")
    assert deploy_mode.is_cloud()


def test_valor_diferente_de_cloud_nao_ativa(monkeypatch):
    monkeypatch.setenv("NBA_DEPLOY_MODE", "local")
    assert not deploy_mode.is_cloud()


def test_secrets_ausentes_nao_quebram(monkeypatch):
    monkeypatch.delenv("NBA_DEPLOY_MODE", raising=False)
    assert deploy_mode._secret_value("QUALQUER_COISA_INEXISTENTE") == ""


def test_nuvem_configura_ambiente_e_descarta_tokens(monkeypatch):
    for name, value in {
        "NBA_DEPLOY_MODE": "cloud",
        "NBA_AUTO_SYNC": "1",
        "GH_TOKEN": "segredo",
        "GITHUB_TOKEN": "segredo",
        "NBA_GITHUB_ARCHIVE_TOKEN": "segredo",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NBA_DATA_HOME", raising=False)
    assert deploy_mode.apply_cloud_environment() is True
    import os

    assert os.environ["NBA_AUTO_SYNC"] == "0"
    assert os.environ["NBA_DATA_HOME"] == "/tmp/nba-data"
    assert not any(name in os.environ for name in ("GH_TOKEN", "GITHUB_TOKEN", "NBA_GITHUB_ARCHIVE_TOKEN"))
    monkeypatch.delenv("NBA_DATA_HOME")


def test_nuvem_usa_diretorio_gravavel_por_padrao(monkeypatch):
    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    monkeypatch.delenv("NBA_DATA_HOME", raising=False)
    assert str(state_root()) == "/tmp/nba-data"
    monkeypatch.setenv("NBA_DATA_HOME", "/tmp/outro")
    assert str(state_root()) == "/tmp/outro"


def test_token_do_arquivo_e_sempre_vazio_na_nuvem(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "segredo")
    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    assert archive_token() == ""
    monkeypatch.setenv("NBA_DEPLOY_MODE", "local")
    assert archive_token() == "segredo"


def test_guarda_somente_leitura_permite_ler_e_bloqueia_escrever(tmp_path, monkeypatch):
    path = tmp_path / "x.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE t (a)")
        connection.execute("INSERT INTO t VALUES (1)")
    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    deploy_mode.install_read_only_guard()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT a FROM t").fetchall() == [(1,)]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO t VALUES (2)")
    with sqlite3.connect(":memory:") as memory:  # bancos em memória não são afetados
        memory.execute("CREATE TABLE m (a)")
    deploy_mode.uninstall_read_only_guard()
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO t VALUES (2)")


def test_conexoes_auxiliares_abrem_sem_escrever_na_nuvem(cloud_data):
    from src.analysis_archive import connect_archive
    from src.history_store import connect_history
    from src.live_store import connect_state
    from src.store import init_db

    deploy_mode.apply_cloud_environment()
    before = {p.name: _sha(p) for p in cloud_data.parent.glob("*") if p.is_file()}
    init_db(cloud_data)  # criação idempotente: não pode falhar nem gravar
    for connect in (connect_history, connect_state, connect_archive):
        connect(cloud_data).close()
    after = {p.name: _sha(p) for p in cloud_data.parent.glob("*") if p.is_file()}
    assert before == after


def test_botoes_de_acao_ficam_desabilitados_na_nuvem(monkeypatch):
    def script():
        import streamlit as st

        from src.ui.cloud import action_button, action_file_uploader

        st.session_state["clicou"] = action_button("Coletar", key="coletar")
        st.session_state["arquivo"] = action_file_uploader("Importar", key="importar")

    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    app = AppTest.from_function(script).run()
    assert app.button(key="coletar").disabled
    assert app.session_state["clicou"] is False and app.session_state["arquivo"] is None


def test_botoes_de_acao_funcionam_no_modo_local(monkeypatch):
    def script():
        import streamlit as st

        from src.ui.cloud import action_button

        if action_button("Coletar", key="coletar"):
            st.write("coletado")

    monkeypatch.delenv("NBA_DEPLOY_MODE", raising=False)
    app = AppTest.from_function(script).run()
    assert not app.button(key="coletar").disabled
    assert app.button(key="coletar").click().run().markdown[0].value == "coletado"


@pytest.mark.parametrize(
    "page",
    [
        "../app.py",
        "../pages/5_Dados_Atualizacoes.py",
        "../pages/8_Palpites.py",
        "../pages/11_Laboratorio.py",
        "../pages/16_Sistema.py",
    ],
)
def test_paginas_abrem_na_nuvem_sem_escrever_no_banco(cloud_data, page):
    before = {p.name: _sha(p) for p in cloud_data.parent.glob("*") if p.is_file()}
    app = AppTest.from_file(page).run(timeout=60)
    assert not app.exception
    after = {p.name: _sha(p) for p in cloud_data.parent.glob("*") if p.is_file()}
    assert before == after
    assert deploy_mode.read_only_active()


def _boot_script():
    import streamlit as st

    from src.ui.cloud import ensure_cloud_data

    ensure_cloud_data()
    st.write("pagina carregou")


def test_sem_dados_e_sem_rede_mostra_mensagem_clara_e_para(tmp_path, monkeypatch):
    from src import cloud_bootstrap
    from src.ui import cloud

    monkeypatch.setenv("NBA_DEPLOY_MODE", "cloud")
    monkeypatch.setenv("NBA_DATA_HOME", str(tmp_path))
    unavailable = cloud_bootstrap.BundleStatus(cloud_bootstrap.STATE_UNAVAILABLE, error="sem rede")
    monkeypatch.setattr(cloud_bootstrap, "sync_bundle", lambda *a, **k: unavailable)
    cloud._synchronized_status.clear()
    app = AppTest.from_function(_boot_script).run()
    assert not app.exception
    assert "ainda não estão disponíveis" in app.error[0].value
    assert not [m for m in app.markdown if "pagina carregou" in m.value]
    cloud._synchronized_status.clear()


def test_dados_antigos_exibem_aviso_com_a_data(cloud_data, monkeypatch):
    from src import cloud_bootstrap
    from src.ui import cloud

    offline = cloud_bootstrap.BundleStatus(
        cloud_bootstrap.STATE_OFFLINE, "v1", "2026-11-08T10:00:00Z", error="x"
    )
    monkeypatch.setattr(cloud_bootstrap, "sync_bundle", lambda *a, **k: offline)
    cloud._synchronized_status.clear()
    app = AppTest.from_function(_boot_script).run()
    assert not app.exception
    assert "dados de 2026-11-08" in app.warning[0].value
    assert [m for m in app.markdown if "pagina carregou" in m.value]


def test_modo_local_nao_consulta_o_release(tmp_path, monkeypatch):
    from src import cloud_bootstrap

    monkeypatch.delenv("NBA_DEPLOY_MODE", raising=False)
    monkeypatch.setattr(deploy_mode, "_secret_value", lambda name: "")

    def forbidden(*a, **k):
        raise AssertionError("não deve consultar o Release fora da nuvem")

    monkeypatch.setattr(cloud_bootstrap, "sync_bundle", forbidden)
    app = AppTest.from_function(_boot_script).run()
    assert not app.exception


def test_rodape_e_estado_dos_dados_na_nuvem(cloud_data):
    from src import cloud_bootstrap as cb

    manifest = cb.BundleManifest(
        "v-abc", "2026-11-09T12:00:00Z", "nba-serving-v-abc.tar.gz", 10, "a" * 64, {"nba.db": 1}
    )
    cb._write_json_atomic(cloud_data.parent / cb.INSTALLED_MANIFEST_NAME, cb._manifest_payload(manifest))
    cb._write_json_atomic(
        cloud_data.parent / cb.STATUS_NAME,
        {
            "state": "offline",
            "version": "v-abc",
            "generated_at": "2026-11-09T12:00:00Z",
            "checked_at": "2026-11-09T13:00:00Z",
            "error": "sem rede",
        },
    )
    app = AppTest.from_file("../pages/16_Sistema.py").run(timeout=60)
    assert not app.exception
    sidebar = " ".join(item.value for item in app.sidebar.caption)
    assert "Dados vv-abc" in sidebar and "09/11/2026 às 09:00" in sidebar
    assert "não são recomendação de aposta" in sidebar
    assert any(m.label == "Versão dos dados" and m.value == "v-abc" for m in app.metric)
    assert "sem rede" in app.warning[0].value


def test_rodape_nao_aparece_no_modo_local(app_db, monkeypatch):
    monkeypatch.delenv("NBA_DEPLOY_MODE", raising=False)
    monkeypatch.setattr(deploy_mode, "_secret_value", lambda name: "")
    app = AppTest.from_file("../pages/16_Sistema.py").run(timeout=60)
    assert not app.exception
    assert not any("não são recomendação" in c.value for c in app.sidebar.caption)
    assert not any(m.label == "Versão dos dados" for m in app.metric)


def test_idade_dos_dados():
    from datetime import UTC, datetime

    from src.ui.cloud import _age_text

    now = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    assert _age_text("2026-11-09T14:30:00Z", now) == "30 min"
    assert _age_text("2026-11-09T12:00:00Z", now) == "3 h"
    assert _age_text("2026-11-07T15:00:00Z", now) == "2 d"
    assert _age_text("lixo", now) == ""
