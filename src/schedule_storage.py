from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

from .nba_schedule import SCHEDULE_COLUMNS

DEFAULT_SCHEDULE_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "nba_schedule.json"
LOGGER = logging.getLogger(__name__)


def read_schedule_cache(path: Path) -> pd.DataFrame:
    """Lê o último calendário válido sem depender dos serviços externos."""
    empty = pd.DataFrame(columns=SCHEDULE_COLUMNS)
    if not path.exists():
        return empty
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            return empty
        frame = pd.DataFrame(records)
        required = {"game_id", "game_date", "home_team_tricode", "away_team_tricode"}
        if not required.issubset(frame.columns):
            return empty
        frame = frame.reindex(columns=SCHEDULE_COLUMNS)
        frame["game_date"] = pd.to_datetime(frame["game_date"], errors="coerce")
        frame["game_datetime_utc"] = pd.to_datetime(frame["game_datetime_utc"], errors="coerce", utc=True)
        return frame.dropna(subset=list(required)).drop_duplicates("game_id", keep="last")
    except (OSError, ValueError, TypeError):
        LOGGER.warning("Não foi possível ler o calendário salvo em %s", path)
        return empty


def save_schedule_cache(schedule: pd.DataFrame, path: Path) -> None:
    """Salva resultados válidos de forma atômica, preservando outras datas."""
    if schedule.empty:
        return
    previous = read_schedule_cache(path)
    frames = [frame for frame in (previous, schedule) if not frame.empty]
    merged = pd.concat(frames, ignore_index=True).drop_duplicates("game_id", keep="last")
    merged = merged.drop_duplicates(["game_date", "home_team_tricode", "away_team_tricode"], keep="last")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(
                merged.reindex(columns=SCHEDULE_COLUMNS).to_json(orient="records", date_format="iso")
            )
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
