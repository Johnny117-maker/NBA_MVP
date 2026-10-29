import copy
import json

import pytest

from src.analysis_archive import archive_snapshot, read_snapshots
from src.remote_archive import (
    BRANCH,
    INDEX,
    ArchiveError,
    GitHubArchive,
    digest,
    envelope,
    import_envelope,
    publish_day,
    sync_remote_archive,
)


def payload():
    return dict(
        game_key="2026-10-29:BOS:NYK",
        day="2026-10-29",
        state="pre",
        home="BOS",
        away="NYK",
        captured_at="2026-10-29T12:00:00+00:00",
        kickoff="2026-10-29T23:00:00+00:00",
        history_end="2026-10-28",
        model={"id": "fixture", "train_end": "2026-10-28"},
        players=[{"player_id": 1, "name": "Atleta", "team": "BOS", "stats": {"pts": {"projected": 20}}}],
    )


class Repository:
    branch = BRANCH

    def __init__(self):
        self.revision = None
        self.versions = {}
        self.trees = {}
        self.commits = {}
        self.calls = []

    def request(self, method, endpoint, *, body=None, missing=False, **kwargs):
        self.calls.append((method, endpoint, copy.deepcopy(body)))
        if method == "GET" and "/git/ref/heads/" in endpoint:
            return {"object": {"sha": self.revision}} if self.revision else None
        if method == "GET" and "/git/commits/" in endpoint:
            return {"tree": {"sha": self.commits[endpoint.split("/")[-1]]}}
        if endpoint == "/git/trees":
            files = copy.deepcopy(self.trees.get(body.get("base_tree"), {}))
            files.update({row["path"]: json.loads(row["content"]) for row in body["tree"]})
            key = "tree" + str(len(self.trees))
            self.trees[key] = files
            return {"sha": key}
        if endpoint == "/git/commits":
            key = "commit" + str(len(self.commits))
            self.commits[key] = body["tree"]
            self.versions[key] = copy.deepcopy(self.trees[body["tree"]])
            return {"sha": key}
        if method in {"POST", "PATCH"} and "/git/refs" in endpoint:
            assert not body.get("force")
            self.revision = body["sha"]
            return {"object": {"sha": self.revision}}
        raise AssertionError((method, endpoint))

    def read_json(self, path, *, ref=None, missing=False):
        value = self.versions.get(ref or self.revision, {}).get(path)
        if value is None and not missing:
            raise AssertionError(path)
        return copy.deepcopy(value)


def test_remote_import_keeps_local_original_and_prefers_remote_without_duplicates(tmp_path):
    path = tmp_path / "nba.db"
    original = payload()
    archive_snapshot(path, original)
    remote = payload()
    remote["captured_at"] = "2026-10-29T13:00:00+00:00"
    remote["players"][0]["stats"]["pts"]["projected"] = 25
    assert import_envelope(path, envelope(remote))
    assert not import_envelope(path, envelope(remote))
    assert len(read_snapshots(path)) == 1
    assert read_snapshots(path)[0]["origin"] == "GitHub"
    assert read_snapshots(path, origin="local")[0]["players"] == original["players"]
    assert len(read_snapshots(path, origin="all")) == 2


def test_bad_hash_and_postgame_capture_are_rejected(tmp_path):
    path = tmp_path / "nba.db"
    document = envelope(payload())
    document["payload"]["players"][0]["name"] = "Alterado"
    with pytest.raises(ArchiveError, match="Hash"):
        import_envelope(path, document)
    body = payload()
    body["captured_at"] = body["kickoff"]
    with pytest.raises(ValueError, match="antes"):
        import_envelope(path, envelope(body))
    assert not read_snapshots(path)


def test_publication_is_atomic_and_never_overwrites_first_prediction():
    repository = Repository()
    first = payload()
    publish_day(repository, first["day"], [first], {"status": "complete"})
    path = "archive/days/2026-10-29/NYK_at_BOS.json"
    stored = repository.read_json(path)
    changed = payload()
    changed["players"][0]["stats"]["pts"]["projected"] = 99
    publish_day(repository, first["day"], [changed], {"status": "complete"})
    assert repository.read_json(path) == stored
    assert repository.read_json(INDEX)["days"][first["day"]]["games"] == 1
    assert len([call for call in repository.calls if call[0] == "PATCH"]) == 1


def test_sync_is_idempotent_and_verifies_manifest_and_file_hashes(tmp_path):
    repository = Repository()
    first = payload()
    publish_day(repository, first["day"], [first], {"status": "complete"})
    path = tmp_path / "nba.db"
    assert sync_remote_archive(path, client=repository)["imported"] == 1
    assert sync_remote_archive(path, client=repository)["inspected"] == 0
    index = repository.versions[repository.revision][INDEX]
    index["days"][first["day"]]["sha256"] = "bad-hash"
    with pytest.raises(ArchiveError, match="Manifesto"):
        sync_remote_archive(path, client=repository)
    assert len(read_snapshots(path)) == 1


def test_transport_does_not_publish_local_metadata_in_payload():
    body = payload()
    body.update(id="local-id", sha256="old-hash", origin="Local")
    assert envelope(body)["sha256"] == digest(payload())


def test_github_failures_do_not_expose_token(monkeypatch):
    import requests

    def fail(*args, **kwargs):
        raise requests.ConnectionError("PRIVATE-PAT")

    monkeypatch.setattr("src.remote_archive.requests.request", fail)
    with pytest.raises(ArchiveError) as result:
        GitHubArchive("PRIVATE-PAT").read_json(INDEX)
    assert "PRIVATE-PAT" not in str(result.value)
    with pytest.raises(ArchiveError, match="Caminho"):
        GitHubArchive("fake").read_json("../secrets.json")
