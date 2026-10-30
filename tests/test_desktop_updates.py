import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from src.desktop_support import initialize_user_data
from src.desktop_updates import UpdateError, check_update, extract_program, prepare_update
from src.remote_archive import REPOSITORY


def program_zip(path, extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("NBAAnalyticsLab/NBAAnalyticsLab.exe", b"program")
        archive.writestr("NBAAnalyticsLab/CRIAR_ATALHO.bat", b"shortcut")
        archive.writestr(
            "NBAAnalyticsLab/package.json",
            json.dumps({"version": "1.5.0", "requires_existing_data": True}),
        )
        for name, data in (extra or {}).items():
            entry = zipfile.ZipInfo(name)
            entry.filename = name
            archive.writestr(entry, data)
    return path.read_bytes()


def test_update_metadata_requires_verified_published_asset():
    release = dict(
        tag_name="v1.5.0",
        assets=[
            dict(
                name="NBAAnalyticsLab-1.5.0-program-Windows-x64.zip",
                state="uploaded",
                digest="sha256:" + "a" * 64,
                size=123,
                id=42,
            )
        ],
    )
    client = SimpleNamespace(repository=REPOSITORY, request=lambda *_: release)
    info = check_update(current="1.4.0", client=client)
    assert info["asset_id"] == 42
    assert info["sha256"] == "a" * 64
    assert check_update(current="1.5.0", client=client)["status"] == "no_update"
    release["assets"][0]["digest"] = None
    with pytest.raises(UpdateError, match="SHA-256"):
        check_update(current="1.4.0", client=client)
    client.repository = "another/repository"
    with pytest.raises(UpdateError, match="autorizado"):
        check_update(current="1.4.0", client=client)


@pytest.mark.parametrize(
    "name",
    [
        "NBAAnalyticsLab/../../outside.txt",
        "/outside.txt",
        "NBAAnalyticsLab/C:/file.txt",
        "NBAAnalyticsLab/dir\\file.txt",
        "NBAAnalyticsLab/_internal/seed/nba.db",
        "NBAAnalyticsLab/_INTERNAL/SEED/nba.db",
        "NBAAnalyticsLab/nbaanalyticslab.EXE",
    ],
)
def test_extract_rejects_unsafe_or_data_bearing_packages_before_writing(tmp_path, name):
    archive = tmp_path / "update.zip"
    program_zip(archive, {name: "untrusted"})
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(UpdateError):
        extract_program(archive, stage, "1.5.0")
    assert not list(stage.iterdir())
    assert not (tmp_path / "outside.txt").exists()


def test_prepare_verifies_hash_and_keeps_old_program_and_personal_data(monkeypatch, tmp_path):
    data = program_zip(tmp_path / "update.zip")
    client = SimpleNamespace(repository=REPOSITORY, token=None)
    profile = tmp_path / "profile"
    (profile / "data").mkdir(parents=True)
    (profile / "data/nba.db").write_bytes(b"personal-history")
    previous = tmp_path / "old/NBAAnalyticsLab.exe"
    previous.parent.mkdir()
    previous.write_bytes(b"old-program")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            yield data

    monkeypatch.setattr("src.desktop_updates.requests.get", lambda *a, **k: Response())
    info = dict(status="available", latest="1.5.0", size=len(data), sha256="0" * 64, asset_id=1)
    with pytest.raises(UpdateError, match="SHA-256"):
        prepare_update(info, profile, client=client)
    assert not (profile / "updates/1.5.0").exists()
    info["sha256"] = hashlib.sha256(data).hexdigest()
    result = prepare_update(info, profile, client=client, previous_executable=previous)
    assert Path(result["executable"]).read_bytes() == b"program"
    assert result["previous_executable"] == str(previous)
    assert previous.read_bytes() == b"old-program"
    assert (profile / "data/nba.db").read_bytes() == b"personal-history"
    assert json.loads((profile / "updates/last_prepared.json").read_text()) == result
    assert not list((profile / "updates").glob(".download-*"))


def test_program_only_package_excludes_seed_and_requires_existing_profile(monkeypatch, tmp_path):
    from scripts import build_desktop

    monkeypatch.setattr(build_desktop, "ROOT", tmp_path)
    target = tmp_path / "dist/NBAAnalyticsLab"
    resources = target / "_internal"
    (resources / "seed/history").mkdir(parents=True)
    (resources / "seed/nba.db").write_bytes(b"big-public-database")
    (resources / "seed/history/public.parquet").write_bytes(b"history")
    (target / "NBAAnalyticsLab.exe").write_bytes(b"program")
    (target / "CRIAR_ATALHO.bat").write_bytes(b"shortcut")
    (target / "package.json").write_text("{}")
    result = build_desktop.package_program_update(target, {"version": "1.5.0", "seed": {"rows": 100}})
    stage = tmp_path / "stage"
    stage.mkdir()
    program = extract_program(Path(result["zip"]), stage, "1.5.0")
    assert not (program / "_internal/seed").exists()
    assert (resources / "seed/nba.db").exists()
    home = tmp_path / "new-profile"
    with pytest.raises(RuntimeError, match="primeira instalação"):
        initialize_user_data(home, program / "_internal")
    assert not home.exists()
    (home / "data").mkdir(parents=True)
    (home / "data/nba.db").write_bytes(b"existing-personal-data")
    initialize_user_data(home, program / "_internal")
    assert (home / "data/nba.db").read_bytes() == b"existing-personal-data"


def test_system_page_checks_updates_only_after_user_action(monkeypatch, tmp_path):
    monkeypatch.setenv("NBA_DATA_HOME", str(tmp_path))
    calls = []

    def check():
        calls.append(True)
        return dict(status="no_update", latest="1.5.0")

    monkeypatch.setattr("src.desktop_updates.check_update", check)
    app = AppTest.from_file("../pages/16_Sistema.py").run()
    assert not app.exception and not calls
    app.button[0].click().run()
    assert not app.exception and calls == [True]
    assert app.success
