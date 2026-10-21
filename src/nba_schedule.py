from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .nba_teams import TEAM_ABBREVIATION_TO_NAME

# The NBA website serves its current schedule as public JSON. The V2_1 file is
# attempted first; V2 remains a fallback because the CDN has used both names.
NBA_SCHEDULE_URLS = (
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
)
SCHEDULE_COLUMNS = [
    "game_id",
    "game_date",
    "game_datetime_utc",
    "game_status",
    "game_status_text",
    "game_label",
    "home_team_tricode",
    "home_team_name",
    "away_team_tricode",
    "away_team_name",
    "arena_name",
]


def _first(record: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return default


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _as_utc_timestamp(value: Any) -> pd.Timestamp | pd.NaT:
    if value in (None, ""):
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return parsed if not pd.isna(parsed) else pd.NaT


def _team_details(team: Any) -> tuple[str | None, str | None]:
    if not isinstance(team, dict):
        return None, None
    tricode = _first(
        team,
        "teamTricode",
        "teamTriCode",
        "teamTricodeName",
        "teamAbbreviation",
        "tricode",
        "abbreviation",
    )
    tricode = str(tricode).strip().upper() if tricode else None
    name = TEAM_ABBREVIATION_TO_NAME.get(tricode or "")
    if not name:
        city = _first(team, "teamCity", "city", default="")
        team_name = _first(team, "teamName", "name", default="")
        combined = " ".join(str(part).strip() for part in (city, team_name) if part)
        name = combined or None
    return tricode, name


def parse_nba_schedule_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """Normalize the NBA CDN schedule JSON into one row per game.

    This function is kept independent from HTTP so the schema can be tested
    with deterministic fixtures and the app can gracefully handle CDN changes.
    """
    root = payload.get("leagueSchedule", payload)
    date_blocks = root.get("gameDates", []) if isinstance(root, dict) else []
    if not isinstance(date_blocks, list):
        raise ValueError("O calendário da NBA não contém uma lista gameDates válida.")

    rows: list[dict[str, Any]] = []
    for date_block in date_blocks:
        if not isinstance(date_block, dict):
            continue
        block_date = _as_date(_first(date_block, "gameDate", "game_date"))
        games = date_block.get("games", [])
        if not isinstance(games, list):
            continue

        for game in games:
            if not isinstance(game, dict):
                continue
            home_code, home_name = _team_details(
                _first(game, "homeTeam", "home_team", default={})
            )
            away_code, away_name = _team_details(
                _first(game, "awayTeam", "away_team", default={})
            )
            game_date = _as_date(
                _first(game, "gameDateEst", "gameDate", "game_date", default=block_date)
            ) or block_date
            if game_date is None or not home_code or not away_code:
                continue

            status_value = _first(game, "gameStatus", "game_status")
            try:
                status = int(status_value) if status_value is not None else None
            except (TypeError, ValueError):
                status = None
            status_text = str(
                _first(game, "gameStatusText", "game_status_text", default="")
            )
            game_time = _as_utc_timestamp(
                _first(
                    game,
                    "gameDateTimeUTC",
                    "gameDateTimeEst",
                    "gameTimeUTC",
                    "gameTimeEst",
                    "game_datetime_utc",
                )
            )
            # If a timestamp without a zone came from the EST field, parsing it
            # as UTC is not correct. The public schedule normally provides the
            # explicit UTC field; when only EST is available, don't use the
            # timestamp to make a time-of-day decision.
            if pd.notna(game_time) and not _first(
                game, "gameDateTimeUTC", "gameTimeUTC", "game_datetime_utc"
            ):
                game_time = pd.NaT

            rows.append(
                {
                    "game_id": str(_first(game, "gameId", "game_id", default="")),
                    "game_date": pd.Timestamp(game_date),
                    "game_datetime_utc": game_time,
                    "game_status": status,
                    "game_status_text": status_text,
                    "game_label": str(
                        _first(game, "gameLabel", "gameSubLabel", "game_label", default="")
                    ),
                    "home_team_tricode": home_code,
                    "home_team_name": home_name or home_code,
                    "away_team_tricode": away_code,
                    "away_team_name": away_name or away_code,
                    "arena_name": str(_first(game, "arenaName", "arena_name", default="")),
                }
            )

    if not rows:
        raise ValueError(
            "Não foi possível interpretar partidas no calendário retornado pela NBA."
        )
    frame = pd.DataFrame(rows, columns=SCHEDULE_COLUMNS)
    frame = frame.drop_duplicates(subset=["game_id", "game_date"]).sort_values(
        ["game_date", "game_datetime_utc"], na_position="last"
    )
    return frame.reset_index(drop=True)


def fetch_nba_schedule(timeout: float = 8.0) -> pd.DataFrame:
    """Download the official public NBA schedule from its CDN.

    Raises RuntimeError with a user-readable message if all endpoint variants
    fail. Callers should cache this function and offer a manual fallback.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
        "Referer": "https://www.nba.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    errors: list[str] = []
    for url in NBA_SCHEDULE_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            frame = parse_nba_schedule_payload(response.json())
            if not frame.empty:
                return frame
            errors.append(f"{url}: calendário vazio")
        except (requests.RequestException, ValueError, TypeError) as error:
            errors.append(f"{url}: {error}")
    summary = "; ".join(errors[-2:])
    raise RuntimeError(
        "Não foi possível consultar o calendário oficial da NBA. "
        "Verifique sua conexão e tente novamente. " + summary
    )


def get_next_game_for_team(
    schedule: pd.DataFrame,
    team_tricode: str,
    now: datetime | date | pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    """Return the next future, not-yet-started scheduled game for a team.

    `now` exists mainly to make the selection deterministic in tests. Pass a
    date to compare only calendar dates, or a timezone-aware datetime for exact
    UTC start-time filtering.
    """
    if schedule is None or schedule.empty or not team_tricode:
        return None
    required = {"game_date", "home_team_tricode", "away_team_tricode"}
    if not required.issubset(schedule.columns):
        return None

    code = str(team_tricode).strip().upper()
    if isinstance(now, date) and not isinstance(now, datetime):
        today = now
        now_utc = None
    elif now is not None:
        timestamp = pd.Timestamp(now)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        now_utc = timestamp.tz_convert("UTC")
        today = now_utc.tz_convert(ZoneInfo("America/New_York")).date()
    else:
        current = datetime.now(timezone.utc)
        now_utc = pd.Timestamp(current)
        today = current.astimezone(ZoneInfo("America/New_York")).date()

    candidates = schedule.copy()
    candidates["game_date"] = pd.to_datetime(candidates["game_date"], errors="coerce")
    candidates = candidates[
        (candidates["home_team_tricode"].astype(str).str.upper() == code)
        | (candidates["away_team_tricode"].astype(str).str.upper() == code)
    ]
    candidates = candidates[candidates["game_date"].dt.date >= today]
    if candidates.empty:
        return None

    # Status 3 is final and status 2 is live. When status is unavailable, use
    # the future date/time; only known finished/in-progress games are excluded.
    if "game_status" in candidates.columns:
        statuses = pd.to_numeric(candidates["game_status"], errors="coerce")
        candidates = candidates[statuses.isna() | (statuses == 1)]
    elif "game_status_text" in candidates.columns:
        status_text = candidates["game_status_text"].astype(str).str.lower()
        candidates = candidates[~status_text.str.contains("final|in progress|live", regex=True)]
    if candidates.empty:
        return None

    if now_utc is not None and "game_datetime_utc" in candidates.columns:
        kickoff = pd.to_datetime(candidates["game_datetime_utc"], errors="coerce", utc=True)
        # If kickoff is available, a same-day tip-off in the past is not the next game.
        future_kickoff = kickoff.isna() | (kickoff >= now_utc)
        candidates = candidates[future_kickoff]
    if candidates.empty:
        return None

    sort_columns = ["game_date"]
    if "game_datetime_utc" in candidates.columns:
        sort_columns.append("game_datetime_utc")
    candidates = candidates.sort_values(sort_columns, na_position="last")
    row = candidates.iloc[0].to_dict()
    is_home = str(row["home_team_tricode"]).upper() == code
    row["is_home_for_team"] = is_home
    row["team_tricode"] = code
    row["opponent_tricode"] = (
        row["away_team_tricode"] if is_home else row["home_team_tricode"]
    )
    row["opponent_name"] = (
        row["away_team_name"] if is_home else row["home_team_name"]
    )
    row["game_date"] = pd.Timestamp(row["game_date"]).date()
    return row
