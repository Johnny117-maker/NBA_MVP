import copy

import pytest

from src.analysis_archive import archive_snapshot, connect_archive, read_snapshots
from src.remote_archive import ArchiveError, digest, publish_day, sync_remote_archive
from src.result_archive import (
    RESULT_INDEX,
    import_results,
    pending_result_days,
    publish_results,
    result_days_to_refresh,
)
from tests.test_remote_archive import Repository, payload


def store_outcome(path, points=22):
    snapshot = read_snapshots(path)[0]
    outcome = dict(
        game_id="actual",
        confirmed_final=True,
        status="Jogou",
        minutes=30,
        actual=dict(pts=points, reb=5, ast=4),
    )
    from src.remote_archive import canonical

    with connect_archive(path) as connection:
        connection.execute(
            "INSERT INTO snapshot_outcomes VALUES (?,?,?,?,?)",
            (
                snapshot["id"],
                1,
                f"2026-10-30T0{points - 20}:00:00+00:00",
                digest(outcome),
                canonical(outcome),
            ),
        )


def test_results_sync_without_local_boxscore_keeps_original_and_appends_correction(tmp_path):
    repository = Repository()
    original = payload()
    publish_day(repository, original["day"], [original], {})
    server, desktop = tmp_path / "server/nba.db", tmp_path / "desktop/nba.db"
    archive_snapshot(server, original)
    assert pending_result_days(server, "2026-10-31") == [original["day"]]
    store_outcome(server)
    assert not pending_result_days(server, "2026-10-31")
    assert publish_results(repository, server)["changed"] == 1
    first_index = repository.read_json(RESULT_INDEX)
    first_path = first_index["games"][original["game_key"]]["path"]
    first_document = repository.read_json(first_path)
    assert publish_results(repository, server)["changed"] == 0
    result = sync_remote_archive(desktop, client=repository)
    assert result["results_imported"] == 1
    assert sync_remote_archive(desktop, client=repository)["results_imported"] == 0
    frozen = read_snapshots(desktop)[0]
    store_outcome(server, points=23)
    publish_results(repository, server)
    assert repository.read_json(first_path) == first_document
    assert sync_remote_archive(desktop, client=repository)["results_imported"] == 1
    assert read_snapshots(desktop)[0] == frozen
    with connect_archive(desktop) as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshot_outcomes").fetchone()[0] == 2
    assert not desktop.exists()  # Nenhum box score local foi necessário.


def test_result_hash_identity_and_final_confirmation_are_checked_atomically(tmp_path):
    repository = Repository()
    original = payload()
    publish_day(repository, original["day"], [original], {})
    path = tmp_path / "nba.db"
    archive_snapshot(path, original)
    store_outcome(path)
    publish_results(repository, path)
    entry = repository.read_json(RESULT_INDEX)["games"][original["game_key"]]
    document = repository.read_json(entry["path"])
    target = tmp_path / "other/nba.db"
    archive_snapshot(target, original)
    bad = copy.deepcopy(document)
    bad["payload"]["records"][0]["outcome"]["actual"]["pts"] = 999
    with pytest.raises(ArchiveError, match="Hash"):
        import_results(target, bad)
    bad = copy.deepcopy(document)
    bad["payload"]["records"][0]["outcome"]["confirmed_final"] = False
    bad["sha256"] = digest(bad["payload"])
    with pytest.raises(ArchiveError, match="confirmação"):
        import_results(target, bad)
    with connect_archive(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshot_outcomes").fetchone()[0] == 0


def test_pending_dates_rotate_and_result_publication_resumes_next_batch(tmp_path):
    path = tmp_path / "nba.db"
    repository = Repository()
    for day in ("2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"):
        snapshot = payload()
        snapshot.update(
            day=day,
            game_key=f"{day}:BOS:NYK",
            captured_at=day + "T12:00:00+00:00",
            kickoff=day + "T23:00:00+00:00",
            history_end="2026-10-24",
        )
        snapshot["model"]["train_end"] = "2026-10-24"
        archive_snapshot(path, snapshot)
        publish_day(repository, day, [snapshot], {})
    visits = [result_days_to_refresh(path, "2026-10-31") for _ in range(3)]
    assert all("2026-10-29" in values for values in visits)
    assert len(set().union(*map(set, visits))) == 5
    for snapshot in read_snapshots(path):
        outcome = dict(
            game_id="actual", confirmed_final=True, status="Sem participação", actual=None, minutes=None
        )
        from src.remote_archive import canonical

        with connect_archive(path) as connection:
            connection.execute(
                "INSERT INTO snapshot_outcomes VALUES (?,?,?,?,?)",
                (snapshot["id"], 1, "2026-10-30T03:00:00+00:00", digest(outcome), canonical(outcome)),
            )
    assert [publish_results(repository, path, batch_size=2)["changed"] for _ in range(4)] == [2, 2, 1, 0]
    assert len(repository.read_json(RESULT_INDEX)["games"]) == 5
