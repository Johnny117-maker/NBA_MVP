from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import requests

from .nba_schedule import ESPN_TRICODE_ALIASES, SCHEDULE_COLUMNS
from .nba_teams import TEAM_ABBREVIATION_TO_NAME

PUBLIC_SCHEDULE_URL = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_schedules/nba_schedule_{season}.csv"
)
PUBLIC_SCHEDULE_SOURCE = "SportsDataverse / ESPN (arquivo público)"


def parse_public_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza o CSV público hoopR/ESPN; não executa conteúdo de colunas textuais."""
    required = {"game_id", "date", "home_abbreviation", "away_abbreviation"}
    if not required.issubset(frame.columns):
        raise ValueError("O arquivo público não possui as colunas de calendário esperadas.")

    def column(name: str) -> pd.Series:
        return frame[name].fillna("").astype(str) if name in frame else pd.Series("", index=frame.index)

    kickoff = pd.to_datetime(column("date"), errors="coerce", utc=True)
    eastern_dates = kickoff.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    dates = pd.to_datetime(column("game_date"), errors="coerce").dt.normalize().fillna(eastern_dates)
    home = column("home_abbreviation").str.strip().str.upper().replace(ESPN_TRICODE_ALIASES)
    away = column("away_abbreviation").str.strip().str.upper().replace(ESPN_TRICODE_ALIASES)
    status = column("status_type_state").str.lower().map({"pre": 1, "in": 2, "post": 3})
    completed = column("status_type_completed").str.lower().eq("true")
    status = status.mask(completed, 3)
    postponed = column("status_type_name").str.contains("POSTPON|CANCEL|SUSPEND", case=False, regex=True)
    status = status.mask(postponed, 4)
    kickoff = kickoff.mask(column("time_valid").str.lower().eq("false"))
    normalized = pd.DataFrame(
        {
            "game_id": column("game_id").str.strip(),
            "game_date": dates,
            "game_datetime_utc": kickoff,
            "game_status": status,
            "game_status_text": column("status_type_detail"),
            "game_label": column("notes_headline"),
            "home_team_tricode": home,
            "home_team_name": home.map(TEAM_ABBREVIATION_TO_NAME),
            "away_team_tricode": away,
            "away_team_name": away.map(TEAM_ABBREVIATION_TO_NAME),
            "arena_name": column("venue_full_name"),
            "schedule_source": PUBLIC_SCHEDULE_SOURCE,
        },
        columns=SCHEDULE_COLUMNS,
    )
    valid = (
        normalized["game_id"].ne("")
        & dates.notna()
        & home.isin(TEAM_ABBREVIATION_TO_NAME)
        & away.isin(TEAM_ABBREVIATION_TO_NAME)
        & home.ne(away)
    )
    result = normalized.loc[valid].drop_duplicates("game_id", keep="last")
    if result.empty:
        raise ValueError("O arquivo público não contém partidas NBA reconhecíveis.")
    return result.sort_values(["game_date", "game_datetime_utc"], na_position="last").reset_index(drop=True)


def fetch_public_schedule(start_date: date, lookahead_days: int = 21, timeout: float = 8.0) -> pd.DataFrame:
    """Obtém arquivos de temporada sem conta/chave, usando o ano final da temporada."""
    end_date = start_date + timedelta(days=max(1, lookahead_days) - 1)
    first_season = start_date.year + int(start_date.month >= 9)
    last_season = end_date.year + int(end_date.month >= 9)
    frames = []
    for season in range(first_season, last_season + 1):
        response = requests.get(
            PUBLIC_SCHEDULE_URL.format(season=season),
            headers={"Accept": "text/csv", "User-Agent": "NBA-Analytics-Lab/0.2"},
            timeout=timeout,
        )
        response.raise_for_status()
        frame = pd.read_csv(BytesIO(response.content), dtype=str, keep_default_na=False)
        frames.append(parse_public_schedule(frame))
    return pd.concat(frames, ignore_index=True).drop_duplicates("game_id", keep="last").reset_index(drop=True)
