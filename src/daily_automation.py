"""Rotina sem interface para GitHub Actions; conserva a primeira captura anterior ao jogo."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import requests

from .analysis_archive import create_daily_snapshots, read_snapshots, resolve_snapshots, snapshot_html
from .data_quality import bulletin_quality, bulletin_usable
from .injuries import injury_snapshot, refresh_injuries
from .live_store import read_live_games
from .live_types import EASTERN, utc_now
from .prop_feedback import refresh_prop_feedback
from .prop_training import ensure_props_bundle, load_research_history
from .remote_archive import SEED_TAG, ArchiveError, GitHubArchive, publish_day, sync_remote_archive
from .season_sync import SeasonSync
from .today_picks import daily_team_picks

SEED_NAME = "NBAAnalyticsLab-prediction-seed.zip"


def bootstrap_seed(db_path: Path, client: GitHubArchive) -> None:
    if db_path.exists():
        with sqlite3.connect(db_path) as connection:
            if connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0] > 100:
                return
        raise ArchiveError("Base de treino insuficiente no cache. Use um diretório de execução novo.")
    release = client.request("GET", "/releases/tags/" + SEED_TAG)
    assets = {item["name"]: item for item in release["assets"]}
    asset = assets[SEED_NAME]
    checksum_asset = assets[SEED_NAME + ".sha256"]
    headers = {"Accept": "application/octet-stream", "Authorization": "Bearer " + client.token}
    api = f"https://api.github.com/repos/{client.repository}/releases/assets/"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    target = db_path.parent / SEED_NAME
    try:
        checksum = requests.get(api + str(checksum_asset["id"]), headers=headers, timeout=(5, 30))
        checksum.raise_for_status()
        expected = checksum.text.split()[0]
        hasher, count = hashlib.sha256(), 0
        with requests.get(api + str(asset["id"]), headers=headers, stream=True, timeout=(5, 60)) as response:
            response.raise_for_status()
            with target.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    count += len(chunk)
                    if count > 150_000_000:
                        raise ArchiveError("Base pública excede o limite de download.")
                    hasher.update(chunk)
                    output.write(chunk)
        if count != asset["size"] or hasher.hexdigest() != expected:
            raise ArchiveError("O SHA-256 da base pública não confere.")
        with zipfile.ZipFile(target) as archive:
            # Não extrai caminhos arbitrários do ZIP nem dados privados.
            for name in ("nba.db", "nba_sync.sqlite"):
                if name not in archive.namelist():
                    continue
                if archive.getinfo(name).file_size > 500_000_000:
                    raise ArchiveError("Arquivo da base pública excede o limite local.")
                destination = (
                    db_path if name == "nba.db" else db_path.with_name(db_path.stem + "_sync.sqlite")
                )
                if not destination.exists():
                    destination.write_bytes(archive.read(name))
    except requests.RequestException:
        raise ArchiveError("Não foi possível baixar a base pública de previsão do GitHub.") from None
    finally:
        target.unlink(missing_ok=True)


def generate_daily_archive(db_path: Path, client: GitHubArchive, output: Path) -> dict:
    moment = utc_now()
    day = moment.astimezone(EASTERN).date().isoformat()
    errors = []
    try:
        sync_remote_archive(db_path, client=client, max_files=240)
    except ArchiveError as error:
        errors.append(str(error))
    # Coleta sem registrar previsões antes de preparar a captura completa.
    sync = SeasonSync(db_path, archive_analysis=False).run_once()
    resolve_snapshots(db_path)
    learning = refresh_prop_feedback(db_path, day)
    refresh_injuries(db_path, force=True)
    _, availability = injury_snapshot(db_path)
    games = read_live_games(db_path, day)
    existing = {item["game_key"] for item in read_snapshots(db_path, day)}
    pending = [
        game
        for game in games
        if game.key not in existing
        and game.state == "pre"
        and game.kickoff
        and pd.Timestamp(game.kickoff) > moment
    ]
    generated = 0
    if pending and bulletin_usable(availability):
        history = load_research_history(db_path, day)
        if not history.empty:
            try:
                model = ensure_props_bundle(history, db_path.parent.parent / "models" / "props")
            except (ImportError, ValueError):
                model = None
            try:
                teams = daily_team_picks(db_path, pending, moment.astimezone(EASTERN).date())
            except ValueError:
                teams = {}
                errors.append("Histórico insuficiente para projetar vencedores e placares.")
            generated = create_daily_snapshots(
                db_path,
                pending,
                history,
                model,
                players_per_team=None,
                team_picks=teams,
                include_other_phases=True,
                capture_context={
                    "engine": "GitHub Actions",
                    "run_url": os.environ.get("NBA_AUTOMATION_RUN_URL", ""),
                    "source_commit": os.environ.get("GITHUB_SHA", ""),
                    "injury_source": availability.get("source"),
                    "injury_reference": availability.get("source_as_of"),
                    "injury_stale": availability.get("stale"),
                },
            )
    elif pending:
        errors.append("Nenhum boletim de lesões válido foi recebido; palpites individuais não gerados.")
    snapshots = read_snapshots(db_path, day)
    captured = {snapshot["game_key"] for snapshot in snapshots}
    missing = [
        dict(
            game_key=game.key,
            state=game.state,
            kickoff=game.kickoff,
            reason="Janela pré-jogo perdida"
            if game.state in {"live", "final"} or (game.kickoff and pd.Timestamp(game.kickoff) <= utc_now())
            else "Aguardando dados elegíveis",
        )
        for game in games
        if game.key not in captured
    ]
    report = dict(
        day=day,
        generated=generated,
        games_found=len(games),
        games_saved=len(snapshots),
        players_saved=sum(len(snapshot["players"]) for snapshot in snapshots),
        missing=missing,
        errors=errors,
        source_errors=sync.get("errors", []),
        run_url=os.environ.get("NBA_AUTOMATION_RUN_URL", ""),
        injury_source=availability.get("source"),
        injury_reference=availability.get("source_as_of"),
        data_quality=bulletin_quality(availability),
        learning=learning,
        status="complete" if games and not missing else "no_games" if not games else "incomplete",
    )
    if not games and not sync.get("live_available") and sync.get("errors"):
        report["status"] = "source_unavailable"
    publication = publish_day(client, day, snapshots, report)
    report["publication"] = publication
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for snapshot in snapshots:
        (output / f"{snapshot['away']}_at_{snapshot['home']}.html").write_text(
            snapshot_html(snapshot), encoding="utf-8"
        )
    resolve_snapshots(db_path)
    return report
