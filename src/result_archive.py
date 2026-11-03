"""Resultados duráveis separados das capturas imutáveis; correções geram novas versões."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .analysis_archive import archive_path, connect_archive, read_snapshots
from .live_store import get_state, set_state
from .live_types import utc_now
from .remote_archive import ArchiveError, canonical, digest, envelope

RESULT_INDEX = "archive/results/index.json"


def pending_result_days(path: str | Path, before_day: str, *, limit: int = 3) -> list[str]:
    if not archive_path(path).exists():
        return []
    with connect_archive(path) as connection:
        rows = connection.execute(
            "SELECT DISTINCT day FROM daily_snapshots s WHERE day<? AND "
            "(SELECT COUNT(DISTINCT player_id) FROM snapshot_outcomes WHERE snapshot_id=s.id "
            "AND json_extract(payload,'$.confirmed_final')=1)"
            "<json_array_length(s.payload,'$.players') ORDER BY day LIMIT ?",
            (before_day, limit),
        ).fetchall()
    return [row[0] for row in rows]


def result_days_to_refresh(path: str | Path, before_day: str) -> list[str]:
    pending = pending_result_days(path, before_day, limit=3650)
    if not pending:
        return []
    cursor = int(get_state(path, "result_day_cursor", 0)) % len(pending)
    selected = [pending[-1]]
    for offset in range(len(pending)):
        value = pending[(cursor + offset) % len(pending)]
        if value not in selected:
            selected.append(value)
        if len(selected) >= min(3, len(pending)):
            break
    set_state(path, "result_day_cursor", (cursor + 2) % len(pending))
    return selected


def _commit(client, revision, entries):
    parent = client.request("GET", "/git/commits/" + revision)
    tree = client.request("POST", "/git/trees", body={"base_tree": parent["tree"]["sha"], "tree": entries})
    commit = client.request(
        "POST",
        "/git/commits",
        body={
            "message": "archive: resultados confirmados e comparacoes",
            "tree": tree["sha"],
            "parents": [revision],
        },
    )
    client.request("PATCH", "/git/refs/heads/" + client.branch, body={"sha": commit["sha"], "force": False})
    return commit["sha"]


def publish_results(client, path: str | Path, *, batch_size: int = 400) -> dict:
    if not 1 <= batch_size <= 400:
        raise ValueError("Lote de publicação deve conter de 1 a 400 partidas.")
    if not archive_path(path).exists():
        return dict(games=0, changed=0)
    head = client.request("GET", "/git/ref/heads/" + client.branch, missing=True)
    if not head or not archive_path(path).exists():
        return dict(games=0, changed=0)
    revision = head["object"]["sha"]
    index = client.read_json(RESULT_INDEX, ref=revision, missing=True) or {"schema_version": 1, "games": {}}
    entries = []
    changed = 0
    manifests = {}
    versions = get_state(path, "published_result_versions", {})
    with connect_archive(path) as connection:
        metadata = connection.execute(
            "SELECT s.id,s.sha256,MAX(o.rowid) FROM daily_snapshots s "
            "JOIN snapshot_outcomes o ON o.snapshot_id=s.id "
            "GROUP BY s.id ORDER BY MAX(o.rowid) DESC"
        ).fetchall()
        candidates = [
            (sid, checksum, revision_id)
            for sid, checksum, revision_id in metadata
            if versions.get(sid) != revision_id
        ][:batch_size]
        for snapshot_id, snapshot_hash, revision_id in candidates:
            snapshot_body = connection.execute(
                "SELECT payload FROM daily_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()[0]
            snapshot = json.loads(snapshot_body)
            if digest(snapshot) != snapshot_hash:
                raise ArchiveError("Captura original corrompida; resultados não publicados.")
            snapshot["id"] = snapshot_id
            versions[snapshot_id] = revision_id
            rows = connection.execute(
                "SELECT o.player_id,o.recorded_at,o.payload FROM snapshot_outcomes o WHERE o.snapshot_id=? "
                "AND o.rowid=(SELECT MAX(n.rowid) FROM snapshot_outcomes n "
                "WHERE n.snapshot_id=o.snapshot_id AND n.player_id=o.player_id)",
                (snapshot["id"],),
            ).fetchall()
            records = [
                dict(player_id=pid, checked_at=stamp, outcome=json.loads(body))
                for pid, stamp, body in rows
                if json.loads(body).get("confirmed_final")
            ]
            if not records:
                continue
            payload = dict(
                game_key=snapshot["game_key"],
                day=snapshot["day"],
                snapshot_sha256=envelope(snapshot)["sha256"],
                records=records,
            )
            day = snapshot["day"]
            if day not in manifests:
                manifests[day] = client.read_json(
                    f"archive/days/{day}/manifest.json", ref=revision, missing=True
                )
            published = (manifests[day] or {}).get("files", [])
            if not any(
                entry["game_key"] == snapshot["game_key"] and entry["sha256"] == payload["snapshot_sha256"]
                for entry in published
            ):
                continue
            checksum = digest(payload)
            previous = index["games"].get(snapshot["game_key"], {})
            if previous.get("sha256") == checksum:
                continue
            if previous.get("snapshot_sha256", payload["snapshot_sha256"]) != payload["snapshot_sha256"]:
                raise ArchiveError("Resultado corresponde a outra captura pré-jogo.")
            filename = (
                f"archive/results/{snapshot['day']}/"
                f"{snapshot['away']}_at_{snapshot['home']}_{checksum[:20]}.json"
            )
            document = dict(payload=payload, sha256=checksum)
            entries.append(dict(path=filename, mode="100644", type="blob", content=canonical(document)))
            index["games"][snapshot["game_key"]] = dict(
                path=filename,
                sha256=checksum,
                snapshot_sha256=payload["snapshot_sha256"],
                players=len(records),
                day=snapshot["day"],
            )
            changed += 1
    if not entries:
        set_state(path, "published_result_versions", versions)
        return dict(games=len(index["games"]), changed=0)
    entries.append(dict(path=RESULT_INDEX, mode="100644", type="blob", content=canonical(index)))
    commit = _commit(client, revision, entries)
    set_state(path, "published_result_versions", versions)
    return dict(games=len(index["games"]), changed=changed, commit=commit)


def import_results(path: str | Path, document: dict) -> int:
    if not isinstance(document, dict):
        raise ArchiveError("Documento de resultados inválido.")
    body = document.get("payload", {})
    if not isinstance(body, dict) or digest(body) != document.get("sha256"):
        raise ArchiveError("Hash de resultado remoto inválido.")
    snapshots = [
        s
        for s in read_snapshots(path, body.get("day"), origin="all")
        if s["game_key"] == body.get("game_key") and s["sha256"] == body.get("snapshot_sha256")
    ]
    if not snapshots:
        raise ArchiveError("A captura original deste resultado ainda não foi importada.")
    snapshot = snapshots[0]
    allowed = {p["player_id"] for p in snapshot["players"]}
    records, seen = body.get("records", []), set()
    if not isinstance(records, list) or len(records) > len(allowed):
        raise ArchiveError("Quantidade de jogadores inválida no resultado.")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("outcome"), dict):
            raise ArchiveError("Formato de resultado inválido.")
        player, outcome = record.get("player_id"), record.get("outcome", {})
        checked = pd.Timestamp(record.get("checked_at"))
        if (
            player not in allowed
            or player in seen
            or checked.tzinfo is None
            or checked < pd.Timestamp(snapshot["kickoff"])
        ):
            raise ArchiveError("Identidade ou horário inválido no resultado remoto.")
        seen.add(player)
        if not outcome.get("confirmed_final") or outcome.get("status") not in {"Jogou", "Sem participação"}:
            raise ArchiveError("Resultado sem confirmação de encerramento.")
        if outcome["status"] == "Jogou":
            actual = outcome.get("actual", {})
            if not isinstance(actual, dict) or any(
                not isinstance(actual.get(stat), (int, float))
                or not math.isfinite(actual[stat])
                or actual[stat] < 0
                or not float(actual[stat]).is_integer()
                for stat in ("pts", "reb", "ast")
            ):
                raise ArchiveError("Estatísticas inválidas no resultado remoto.")
            minutes = outcome.get("minutes")
            if not isinstance(minutes, (int, float)) or not math.isfinite(minutes) or minutes <= 0:
                raise ArchiveError("Minutos inválidos no resultado remoto.")
        elif outcome.get("actual") is not None:
            raise ArchiveError("Ausência não pode ser transformada em produção zero.")
    imported = 0
    with connect_archive(path) as connection:
        for record in records:
            player, outcome = record["player_id"], record["outcome"]
            fingerprint = digest(outcome)
            latest = connection.execute(
                "SELECT recorded_at,fingerprint FROM snapshot_outcomes WHERE snapshot_id=? AND player_id=? "
                "ORDER BY rowid DESC LIMIT 1",
                (snapshot["id"], player),
            ).fetchone()
            if latest and pd.Timestamp(latest[0]) > pd.Timestamp(record["checked_at"]):
                continue
            if not latest or latest[1] != fingerprint:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO snapshot_outcomes VALUES (?,?,?,?,?)",
                    (snapshot["id"], player, record["checked_at"], fingerprint, canonical(outcome)),
                )
                imported += int(cursor.rowcount > 0)
            connection.execute(
                "INSERT OR REPLACE INTO remote_result_authority VALUES (?,?,?)",
                (snapshot["id"], player, utc_now().isoformat()),
            )
    return imported


def sync_results(path: str | Path, client, revision: str, *, max_files: int = 60) -> dict:
    index = client.read_json(RESULT_INDEX, ref=revision, missing=True)
    if not index:
        return dict(imported=0, inspected=0)
    if not isinstance(index, dict) or not isinstance(index.get("games"), dict):
        raise ArchiveError("Índice de resultados inválido.")
    cache = get_state(path, "remote_result_cache", {})
    imported, inspected = 0, 0
    for game, entry in sorted(index.get("games", {}).items(), key=lambda item: item[1]["day"], reverse=True):
        if inspected >= max_files:
            break
        if cache.get(game) == entry["sha256"]:
            continue
        inspected += 1
        document = client.read_json(entry["path"], ref=revision)
        if document.get("sha256") != entry["sha256"]:
            raise ArchiveError("Resultado divergente do índice remoto.")
        try:
            imported += import_results(path, document)
        except ArchiveError as error:
            if "ainda não foi importada" in str(error):
                continue
            raise
        cache[game] = entry["sha256"]
    set_state(path, "remote_result_cache", cache)
    result = dict(imported=imported, inspected=inspected, checked_at=utc_now().isoformat())
    set_state(path, "remote_result_status", result)
    return result
