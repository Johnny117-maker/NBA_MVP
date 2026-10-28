"""Contrato de dados comum às fontes, sem misturar identificadores de provedores."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
STAT_FIELDS = (
    "pts",
    "oreb",
    "dreb",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def current_season(day: date | None = None) -> str:
    day = day or utc_now().astimezone(EASTERN).date()
    year = day.year if day.month >= 9 else day.year - 1
    return f"{year}-{(year + 1) % 100:02d}"


def number(value: object) -> float | None:
    try:
        result = float(str(value))
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def minutes(value: object) -> float | None:
    raw = "" if value is None else str(value).strip()
    iso = re.fullmatch(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", raw)
    if iso and any(iso.groups()):
        return float(iso[1] or 0) + float(iso[2] or 0) / 60
    if re.fullmatch(r"\d+:\d{2}(?:\.\d+)?", raw):
        whole, seconds = raw.split(":")
        return float(whole) + float(seconds) / 60
    return number(raw)


@dataclass
class LivePlayer:
    external_id: str
    name: str
    team: str
    minutes: float | None
    stats: dict[str, float | None]
    canonical_id: int | None = None
    starter: bool | None = None
    ejected: bool = False
    on_court: bool | None = None


@dataclass
class LiveGame:
    external_id: str
    source: str
    day: str
    season: str
    home: str
    away: str
    state: str
    fetched_at: str
    home_score: int | None = None
    away_score: int | None = None
    period: int = 0
    clock_minutes: float | None = None
    kickoff: str | None = None
    boxscore_at: str | None = None
    source_updated_at: str | None = None
    regular_season: bool = True
    archive: bool = False
    players: list[LivePlayer] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.day}:{self.home}:{self.away}"

    @property
    def elapsed(self) -> float | None:
        if self.period < 1 or self.clock_minutes is None:
            return None
        length = 12 if self.period <= 4 else 5
        if not 0 <= self.clock_minutes <= length:
            return None
        before = (self.period - 1) * 12 if self.period <= 4 else 48 + (self.period - 5) * 5
        return before + length - self.clock_minutes

    @property
    def remaining(self) -> float | None:
        elapsed = self.elapsed
        if elapsed is None:
            return None
        duration = 48 + max(0, self.period - 4) * 5
        return max(0.0, duration - elapsed)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> LiveGame:
        return cls(**{**value, "players": [LivePlayer(**row) for row in value.get("players", [])]})

    def fresh(self, now: datetime, max_age: int = 120) -> bool:
        if self.archive or not self.boxscore_at:
            return False
        stamps = [self.boxscore_at]
        if self.source_updated_at:
            stamps.append(self.source_updated_at)
        try:
            return all(
                0 <= (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() <= max_age
                for stamp in stamps
            )
        except (TypeError, ValueError):
            return False
