import hashlib
import io
import json
import tarfile

import pytest
import requests

from src import cloud_bootstrap as cb

BASE = "https://exemplo.invalido/releases/download/data-latest"


def make_bundle(files: dict[str, bytes], tmp_path, version="v1"):
    """Pacote .tar.gz + manifesto coerentes entre si."""
    archive = tmp_path / f"fonte-{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))
    data = archive.read_bytes()
    manifest = {
        "version": version,
        "generated_at": "2026-11-09T12:00:00Z",
        "asset": {
            "name": "nba-serving.tar.gz",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "files": [{"name": n, "bytes": len(c)} for n, c in files.items()],
    }
    return data, manifest


class FakeResponse:
    def __init__(self, status=200, body=b"", fail_after=None):
        self.status_code = status
        self._body = body
        self.text = body.decode("utf-8", "replace")
        self._fail_after = fail_after

    def iter_content(self, chunk_size=1):
        step = 7
        for start in range(0, len(self._body), step):
            if self._fail_after is not None and start >= self._fail_after:
                raise requests.ConnectionError("conexão interrompida")
            yield self._body[start : start + step]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        result = self.routes[url.rsplit("/", 1)[-1]]
        if isinstance(result, Exception):
            raise result
        return result() if callable(result) else result

    def close(self):
        pass


def routes_for(data, manifest, **extra):
    return {
        "manifest.json": FakeResponse(200, json.dumps(manifest).encode()),
        "nba-serving.tar.gz": FakeResponse(200, data),
        **extra,
    }


FILES = {"nba.db": b"banco-principal", "nba_sync.sqlite": b"sync"}


def test_primeiro_acesso_baixa_confere_e_instala(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    target = tmp_path / "data"
    status = cb.sync_bundle(FakeSession(routes_for(data, manifest)), target, BASE)
    assert status.state == cb.STATE_UPDATED and status.version == "v1"
    assert (target / "nba.db").read_bytes() == b"banco-principal"
    assert (target / "nba_sync.sqlite").read_bytes() == b"sync"
    assert cb.read_installed_manifest(target).version == "v1"
    assert cb.read_status(target).state == cb.STATE_UPDATED
    assert not [p for p in target.iterdir() if p.name.startswith(".download-")]


def test_sem_novidade_nao_baixa_o_pacote(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    target = tmp_path / "data"
    cb.sync_bundle(FakeSession(routes_for(data, manifest)), target, BASE)
    session = FakeSession(routes_for(data, manifest))
    status = cb.sync_bundle(session, target, BASE)
    assert status.state == cb.STATE_CURRENT
    assert session.calls == [f"{BASE}/manifest.json"]


def test_versao_nova_substitui_os_arquivos(tmp_path):
    old, old_manifest = make_bundle(FILES, tmp_path, "v1")
    target = tmp_path / "data"
    cb.sync_bundle(FakeSession(routes_for(old, old_manifest)), target, BASE)
    new, new_manifest = make_bundle({"nba.db": b"novo", "nba_sync.sqlite": b"novo-sync"}, tmp_path, "v2")
    status = cb.sync_bundle(FakeSession(routes_for(new, new_manifest)), target, BASE)
    assert status.state == cb.STATE_UPDATED and status.version == "v2"
    assert (target / "nba.db").read_bytes() == b"novo"


def test_rede_fora_com_dados_locais_continua_mostrando_a_versao_anterior(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    target = tmp_path / "data"
    cb.sync_bundle(FakeSession(routes_for(data, manifest)), target, BASE)
    down = FakeSession({"manifest.json": requests.ConnectionError("sem rede")})
    status = cb.sync_bundle(down, target, BASE)
    assert status.state == cb.STATE_OFFLINE and status.version == "v1" and "sem rede" in status.error
    assert (target / "nba.db").read_bytes() == b"banco-principal"
    assert cb.read_status(target).state == cb.STATE_OFFLINE


def test_rede_fora_sem_dados_retorna_estado_claro_sem_excecao(tmp_path):
    down = FakeSession({"manifest.json": requests.Timeout("lento")})
    status = cb.sync_bundle(down, tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE and not status.has_data and status.error


def test_manifesto_ausente_404(tmp_path):
    session = FakeSession({"manifest.json": FakeResponse(404)})
    status = cb.sync_bundle(session, tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE and "manifest.json" in status.error


@pytest.mark.parametrize("body", [b"nao e json", b'{"version": "x"}', b"[]"])
def test_manifesto_invalido(tmp_path, body):
    session = FakeSession({"manifest.json": FakeResponse(200, body)})
    status = cb.sync_bundle(session, tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE


def test_checksum_invalido_nao_instala_e_preserva_o_banco_anterior(tmp_path):
    old, old_manifest = make_bundle(FILES, tmp_path, "v1")
    target = tmp_path / "data"
    cb.sync_bundle(FakeSession(routes_for(old, old_manifest)), target, BASE)
    new, new_manifest = make_bundle({"nba.db": b"novo"}, tmp_path, "v2")
    adulterado = new[:-1] + bytes([new[-1] ^ 1])  # mesmo tamanho, conteúdo diferente
    status = cb.sync_bundle(FakeSession(routes_for(adulterado, new_manifest)), target, BASE)
    assert status.state == cb.STATE_OFFLINE and "confere" in status.error
    assert (target / "nba.db").read_bytes() == b"banco-principal"
    assert cb.read_installed_manifest(target).version == "v1"
    assert not [p for p in target.iterdir() if p.name.startswith(".download-")]


def test_checksum_invalido_no_primeiro_acesso_fica_indisponivel(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    manifest["asset"]["sha256"] = "0" * 64
    status = cb.sync_bundle(FakeSession(routes_for(data, manifest)), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE
    assert not (tmp_path / "data" / "nba.db").exists()


def test_download_interrompido_apaga_o_parcial_e_nao_instala(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    routes = routes_for(data, manifest, **{"nba-serving.tar.gz": FakeResponse(200, data, fail_after=14)})
    target = tmp_path / "data"
    status = cb.sync_bundle(FakeSession(routes), target, BASE)
    assert status.state == cb.STATE_UNAVAILABLE and "interrompido" in status.error
    assert not (target / "nba.db").exists()
    assert not [p for p in target.iterdir() if p.name.startswith(".download-")]


def test_pacote_maior_que_o_declarado_e_rejeitado(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    manifest["asset"]["bytes"] = len(data) - 5
    status = cb.sync_bundle(FakeSession(routes_for(data, manifest)), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE and "tamanho" in status.error


def test_http_de_erro_no_download(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    routes = routes_for(data, manifest, **{"nba-serving.tar.gz": FakeResponse(403)})
    status = cb.sync_bundle(FakeSession(routes), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE and "403" in status.error


def test_falha_passageira_do_servidor_e_repetida(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    answers = iter([FakeResponse(503), FakeResponse(200, json.dumps(manifest).encode())])
    routes = routes_for(data, manifest, **{"manifest.json": lambda: next(answers)})
    status = cb.sync_bundle(FakeSession(routes), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UPDATED


def test_pacote_com_caminho_perigoso_e_rejeitado(tmp_path):
    data, manifest = make_bundle({"nba.db": b"x"}, tmp_path)
    archive = tmp_path / "ruim.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("../fora.db")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    manifest2 = dict(manifest)
    payload = archive.read_bytes()
    manifest2["asset"] = {
        "name": "nba-serving.tar.gz",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    status = cb.sync_bundle(FakeSession(routes_for(payload, manifest2)), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE
    assert not (tmp_path / "fora.db").exists()


def test_arquivo_listado_mas_ausente_no_pacote(tmp_path):
    data, manifest = make_bundle({"nba.db": b"x"}, tmp_path)
    manifest["files"].append({"name": "nba_sync.sqlite", "bytes": 3})
    status = cb.sync_bundle(FakeSession(routes_for(data, manifest)), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE and "ausentes" in status.error


def test_pacote_corrompido(tmp_path):
    junk = b"isto nao e tar"
    manifest = {
        "version": "v1",
        "generated_at": "x",
        "asset": {
            "name": "nba-serving.tar.gz",
            "bytes": len(junk),
            "sha256": hashlib.sha256(junk).hexdigest(),
        },
        "files": [{"name": "nba.db", "bytes": 1}],
    }
    status = cb.sync_bundle(FakeSession(routes_for(junk, manifest)), tmp_path / "data", BASE)
    assert status.state == cb.STATE_UNAVAILABLE and "corrompido" in status.error


def test_url_padrao_usa_o_repositorio_configurado_e_permite_sobrescrever(monkeypatch):
    monkeypatch.delenv(cb.BUNDLE_BASE_URL_ENV, raising=False)
    monkeypatch.setenv("NBA_ARCHIVE_REPOSITORY", "dono/repo")
    assert cb.release_base_url() == "https://github.com/dono/repo/releases/download/data-latest"
    monkeypatch.setenv(cb.BUNDLE_BASE_URL_ENV, "https://espelho.example/x/")
    assert cb.release_base_url() == "https://espelho.example/x"


def test_nunca_envia_cabecalho_de_autenticacao(tmp_path):
    data, manifest = make_bundle(FILES, tmp_path)
    seen = []

    class Spy(FakeSession):
        def get(self, url, **kwargs):
            seen.append(kwargs)
            return super().get(url, **kwargs)

    cb.sync_bundle(Spy(routes_for(data, manifest)), tmp_path / "data", BASE)
    assert seen and all("headers" not in kwargs for kwargs in seen)
