from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
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
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
LOGGER = logging.getLogger(__name__)

# ESPN uses a few different abbreviations in some endpoints. Normalize these to
# the same tricodes stored in the project database.
ESPN_TRICODE_ALIASES = {
    "GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS",
    "UTAH": "UTA", "WSH": "WAS",
}

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
    "schedule_source",
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
                    "schedule_source": "NBA oficial",
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


def _espn_game_date(value: Any) -> date | None:
    """Parse an ESPN event date into the NBA local game day (US Eastern)."""
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return _as_date(value)
    return parsed.tz_convert(ZoneInfo("America/New_York")).date()


def parse_espn_scoreboard_payload(payload: dict[str, Any]) -> pd.DataFrame:
    """Normalize the public ESPN NBA scoreboard into the common schedule schema."""
    events = payload.get("events", []) if isinstance(payload, dict) else []
    if not isinstance(events, list):
        raise ValueError("O placar da ESPN não contém uma lista válida de eventos.")

    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
        competitors = competition.get("competitors") or []
        if not isinstance(competitors, list):
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if home is None or away is None:
            continue

        def team_info(item: dict[str, Any]) -> tuple[str | None, str | None]:
            team = item.get("team") or {}
            abbreviation = _first(team, "abbreviation")
            name = _first(team, "displayName", "name", "shortDisplayName")
            raw_code = str(abbreviation).strip().upper() if abbreviation else None
            code = ESPN_TRICODE_ALIASES.get(raw_code or "", raw_code)
            if code not in TEAM_ABBREVIATION_TO_NAME:
                normalized_name = str(name or "").strip().casefold()
                code = next(
                    (
                        known_code
                        for known_code, known_name in TEAM_ABBREVIATION_TO_NAME.items()
                        if known_name.casefold() == normalized_name
                    ),
                    None,
                )
            if not name and code:
                name = TEAM_ABBREVIATION_TO_NAME.get(code, code)
            return code, str(name) if name else None

        home_code, home_name = team_info(home)
        away_code, away_name = team_info(away)
        event_date = _first(competition, "date", default=_first(event, "date"))
        game_day = _espn_game_date(event_date)
        if not game_day or not home_code or not away_code:
            continue

        kickoff = _as_utc_timestamp(event_date)
        status_object = competition.get("status") or event.get("status") or {}
        status_type = status_object.get("type") or {}
        state = str(_first(status_type, "state", default="")).lower()
        status_lookup = {"pre": 1, "in": 2, "post": 3}
        status_code = status_lookup.get(state)
        if status_code is None and status_type.get("completed") is True:
            status_code = 3
        venue = competition.get("venue") or {}
        rows.append(
            {
                "game_id": str(_first(event, "id", default=_first(competition, "id", default=""))),
                "game_date": pd.Timestamp(game_day),
                "game_datetime_utc": kickoff,
                "game_status": status_code,
                "game_status_text": str(_first(status_type, "detail", "description", default="")),
                "game_label": str(_first(event, "name", "shortName", default="")),
                "home_team_tricode": home_code,
                "home_team_name": home_name or home_code,
                "away_team_tricode": away_code,
                "away_team_name": away_name or away_code,
                "arena_name": str(_first(venue, "fullName", "name", default="")),
                "schedule_source": "ESPN (alternativo)",
            }
        )

    if not rows:
        raise ValueError("A resposta da ESPN não continha jogos NBA reconhecíveis.")
    frame = pd.DataFrame(rows, columns=SCHEDULE_COLUMNS)
    frame = frame.drop_duplicates(subset=["game_id", "game_date"]).sort_values(
        ["game_date", "game_datetime_utc"], na_position="last"
    )
    return frame.reset_index(drop=True)


def _fetch_espn_schedule(
    *,
    team_tricode: str | None,
    start_date: date,
    lookahead_days: int,
    timeout: float,
) -> pd.DataFrame:
    """Fallback to ESPN's public scoreboard and stop once the team's next game is found.

    A compact date-range request is attempted first. Since date-range behavior can
    vary by scoreboard deployment, the code falls back to one request per day.
    """
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.espn.com",
        "Referer": "https://www.espn.com/nba/",
    }
    frames: list[pd.DataFrame] = []
    errors: list[str] = []

    # Try one compact date-range request first. Some ESPN scoreboard deployments
    # reject ranges, so daily requests remain the reliable fallback below.
    range_end = start_date + timedelta(days=max(1, lookahead_days) - 1)
    try:
        range_response = requests.get(
            ESPN_SCOREBOARD_URL,
            params={
                "dates": f"{start_date:%Y%m%d}-{range_end:%Y%m%d}",
                "limit": "100",
            },
            headers=headers,
            timeout=min(timeout, 3.0),
        )
        range_response.raise_for_status()
        range_payload = range_response.json()
        if isinstance(range_payload, dict) and range_payload.get("events"):
            range_frame = parse_espn_scoreboard_payload(range_payload)
            frames.append(range_frame)
            # A successful range response is already the complete requested
            # scoreboard window. Return it when it contains the requested team,
            # even if that team's game has just gone final; get_next_game_for_team
            # remains responsible for excluding completed games from "next game"
            # selection. This also avoids redundant per-day requests.
            contains_team = (
                not team_tricode
                or team_tricode.upper() in set(range_frame["home_team_tricode"].astype(str).str.upper())
                or team_tricode.upper() in set(range_frame["away_team_tricode"].astype(str).str.upper())
            )
            if contains_team:
                return range_frame
    except (requests.RequestException, ValueError, TypeError) as error:
        errors.append(f"ESPN intervalo: {type(error).__name__}")

    for day_offset in range(max(1, lookahead_days)):
        game_day = start_date + timedelta(days=day_offset)
        try:
            response = requests.get(
                ESPN_SCOREBOARD_URL,
                params={"dates": game_day.strftime("%Y%m%d"), "limit": "100"},
                headers=headers,
                timeout=min(timeout, 2.5),
            )
            response.raise_for_status()
            payload = response.json()
            events = payload.get("events", []) if isinstance(payload, dict) else []
            if not events:
                continue
            frame = parse_espn_scoreboard_payload(payload)
            frames.append(frame)
            if team_tricode and get_next_game_for_team(
                pd.concat(frames, ignore_index=True), team_tricode
            ) is not None:
                break
        except (requests.RequestException, ValueError, TypeError) as error:
            # Continue through the window: a single bad date should not kill lookup.
            errors.append(f"{game_day:%Y-%m-%d}: {type(error).__name__}")
            continue

    if not frames:
        summary = ", ".join(errors[-3:]) if errors else "nenhum jogo retornado"
        raise RuntimeError(f"ESPN indisponível ({summary}).")
    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["game_id", "game_date"]).sort_values(
        ["game_date", "game_datetime_utc"], na_position="last"
    )
    return result.reset_index(drop=True)


def fetch_nba_schedule(
    timeout: float = 8.0,
    team_tricode: str | None = None,
    lookahead_days: int = 21,
) -> pd.DataFrame:
    """Fetch NBA schedule, falling back to ESPN if the NBA CDN is unreachable.

    The source column marks whether rows came from NBA CDN or the ESPN fallback.
    Raises a concise RuntimeError if neither source is available.
    """
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
        "Referer": "https://www.nba.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    errors: list[str] = []
    for url in NBA_SCHEDULE_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=min(timeout, 4.0))
            response.raise_for_status()
            frame = parse_nba_schedule_payload(response.json())
            if not frame.empty:
                return frame
            errors.append("NBA CDN: calendário vazio")
        except (requests.RequestException, ValueError, TypeError) as error:
            errors.append(f"NBA CDN {url.rsplit('/', 1)[-1]}: {type(error).__name__}")

    # The official NBA CDN can be blocked/reset by some home or corporate networks.
    # Use ESPN as an alternate source rather than making the user fill every field.
    try:
        now_et = datetime.now(ZoneInfo("America/New_York")).date()
        return _fetch_espn_schedule(
            team_tricode=team_tricode,
            start_date=now_et,
            lookahead_days=lookahead_days,
            timeout=min(timeout, 2.5),
        )
    except RuntimeError as error:
        errors.append(str(error))
        LOGGER.warning("Falha ao consultar calendário NBA/ESPN: %s", "; ".join(errors))
        raise RuntimeError(
            "Não foi possível consultar o calendário automaticamente nas fontes NBA e ESPN. "
            "A rede pode estar bloqueando esses serviços. Preencha o adversário e a data manualmente "
            "ou tente novamente em outra conexão."
        ) from error


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
        current = datetime.now(UTC)
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
