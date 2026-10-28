"""Adaptadores públicos e opcionais. Nunca expõe URLs autenticadas nos erros."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from .live_store import cache_get, cache_put, reserve_usage
from .live_types import EASTERN, LiveGame, LivePlayer, current_season, minutes, number, utc_now
from .nba_schedule import ESPN_TRICODE_ALIASES
from .nba_teams import TEAM_ABBREVIATION_TO_NAME

NBA_BOARD = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
NBA_BOX = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ARCHIVE_BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiKeys:
    api_sports: str = field(default="", repr=False)
    rapidapi: str = field(default="", repr=False)
    balldontlie: str = field(default="", repr=False)
    odds: str = field(default="", repr=False)
    bdl_plan: str = "free"


class FeedClient:
    def __init__(self, db_path: str | Path, keys: ApiKeys | None = None):
        self.db_path = Path(db_path)
        self.keys = keys or ApiKeys()

    def get(
        self,
        provider: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        ttl: int = 0,
        cost: int = 1,
        csv: bool = False,
    ):
        auth_hash = hashlib.sha256(repr(sorted((headers or {}).items())).encode()).hexdigest()[:12]
        safe_params = {key: val for key, val in (params or {}).items() if key != "apiKey"}
        if params and params.get("apiKey"):
            auth_hash += hashlib.sha256(str(params["apiKey"]).encode()).hexdigest()[:12]
        key = provider + url + json.dumps(safe_params, sort_keys=True) + auth_hash
        if ttl:
            cached = cache_get(self.db_path, key, ttl)
            if cached is not None:
                return (
                    pd.read_csv(StringIO(cached), dtype=str, keep_default_na=False)
                    if csv
                    else json.loads(cached)
                )
        now = utc_now()
        if provider in {"API-Sports", "balldontlie", "The Odds API"}:
            costs = (
                {now.date().isoformat(): (1, 95)}
                if provider == "API-Sports"
                else {now.strftime("%Y-%m-%dT%H:%M"): (1, 5)}
                if provider == "balldontlie"
                else {now.date().isoformat(): (cost, 12), now.strftime("%Y-%m"): (cost, 450)}
            )
            if not reserve_usage(self.db_path, provider + ":" + auth_hash, costs):
                raise ProviderError(f"{provider}: limite local de consultas atingido.")
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": "NBA-Analytics-Lab/0.3", **(headers or {})},
                timeout=(3, 12),
            )
            if not response.ok:
                raise ProviderError(f"{provider}: HTTP {response.status_code}.")
            if len(response.content) > 25_000_000:
                raise ProviderError(f"{provider}: resposta maior que o limite local.")
            if csv:
                body = response.content.decode("utf-8-sig")
                result = pd.read_csv(StringIO(body), dtype=str, keep_default_na=False)
            else:
                result = response.json()
                if isinstance(result, dict) and result.get("errors"):
                    raise ProviderError(f"{provider}: consulta recusada ou cota esgotada.")
                body = json.dumps(result)
        except (requests.RequestException, ValueError, UnicodeError) as error:
            raise ProviderError(f"{provider}: fonte indisponível ({type(error).__name__}).") from None
        if ttl:
            cache_put(self.db_path, key, body)
        return result

    def archive(self, dataset: str, season_end: int) -> pd.DataFrame:
        files = {
            "schedule": ("espn_nba_schedules", f"nba_schedule_{season_end}.csv"),
            "players": ("espn_nba_player_boxscores", f"player_box_{season_end}.csv"),
            "crosswalk": ("nba_crosswalk", f"nba_player_crosswalk_{season_end}.csv"),
        }
        tag, filename = files[dataset]
        return self.get("SportsDataverse/ESPN", f"{ARCHIVE_BASE}/{tag}/{filename}", ttl=3600, csv=True)


def team_code(value: object) -> str:
    raw = str(value or "").strip().upper()
    names = {"LOS ANGELES CLIPPERS": "LAC", "LA LAKERS": "LAL"}
    if raw in names:
        return names[raw]
    code = ESPN_TRICODE_ALIASES.get(raw, raw)
    if code in TEAM_ABBREVIATION_TO_NAME:
        return code
    return next((key for key, name in TEAM_ABBREVIATION_TO_NAME.items() if name.upper() == raw), "")


def _day(value: str) -> str:
    stamp = pd.to_datetime(value, utc=True, errors="raise")
    return stamp.tz_convert(EASTERN).date().isoformat()


def _integer(value: object) -> int | None:
    result = number(value)
    return int(result) if result is not None else None


def parse_nba_board(payload: dict, now: datetime | None = None) -> list[LiveGame]:
    now = now or utc_now()
    board = payload.get("scoreboard", {})
    if not isinstance(board.get("games"), list):
        raise ProviderError("NBA: formato inesperado do placar.")
    games = []
    for row in board["games"]:
        home, away = row.get("homeTeam", {}), row.get("awayTeam", {})
        home_code, away_code = team_code(home.get("teamTricode")), team_code(away.get("teamTricode"))
        if not home_code or not away_code:
            continue
        kickoff = row.get("gameTimeUTC")
        day = _day(kickoff) if kickoff else str(board.get("gameDate", ""))[:10]
        if not day:
            continue
        game_id = str(row.get("gameId", ""))
        state = {1: "pre", 2: "live", 3: "final"}.get(row.get("gameStatus"), "unavailable")
        games.append(
            LiveGame(
                game_id,
                "NBA",
                day,
                current_season(date.fromisoformat(day)),
                home_code,
                away_code,
                state,
                now.isoformat(),
                _integer(home.get("score")),
                _integer(away.get("score")),
                int(row.get("period") or 0),
                minutes(row.get("gameClock")),
                kickoff,
                regular_season=game_id.startswith("002"),
            )
        )
    return games


def attach_nba_box(game: LiveGame, payload: dict, now: datetime | None = None) -> LiveGame:
    raw = payload.get("game", {})
    if str(raw.get("gameId")) != game.external_id:
        raise ProviderError("NBA: identificador divergente no boxscore.")
    players = []
    keys = {
        "pts": "points",
        "oreb": "reboundsOffensive",
        "dreb": "reboundsDefensive",
        "reb": "reboundsTotal",
        "ast": "assists",
        "stl": "steals",
        "blk": "blocks",
        "tov": "turnovers",
        "pf": "foulsPersonal",
        "fgm": "fieldGoalsMade",
        "fga": "fieldGoalsAttempted",
        "fg3m": "threePointersMade",
        "fg3a": "threePointersAttempted",
        "ftm": "freeThrowsMade",
        "fta": "freeThrowsAttempted",
    }
    for side in ("homeTeam", "awayTeam"):
        team = raw.get(side, {})
        code = team_code(team.get("teamTricode"))
        if code != (game.home if side == "homeTeam" else game.away):
            raise ProviderError("NBA: equipes divergentes no boxscore.")
        for player in team.get("players", []):
            stats = player.get("statistics", {})
            players.append(
                LivePlayer(
                    str(player.get("personId", "")),
                    str(player.get("name", "")),
                    code,
                    minutes(stats.get("minutes")),
                    {key: number(stats.get(value)) for key, value in keys.items()},
                    starter=player.get("starter") == "1",
                    on_court=player.get("oncourt") == "1",
                )
            )
    game.players = players
    game.boxscore_at = (now or utc_now()).isoformat()
    source_time = pd.to_datetime(payload.get("meta", {}).get("time"), utc=True, errors="coerce")
    if source_time is not None and not pd.isna(source_time):
        game.source_updated_at = source_time.isoformat()
    game.period = int(raw.get("period") or game.period)
    game.clock_minutes = minutes(raw.get("gameClock"))
    # O relógio e o placar vêm do mesmo boxscore para evitar combinar instantes diferentes.
    game.home_score = _integer(raw.get("homeTeam", {}).get("score"))
    game.away_score = _integer(raw.get("awayTeam", {}).get("score"))
    game.state = {1: "pre", 2: "live", 3: "final"}.get(raw.get("gameStatus"), game.state)
    return game


def parse_espn_board(payload: dict, now: datetime | None = None) -> list[LiveGame]:
    now = now or utc_now()
    if not isinstance(payload.get("events"), list):
        raise ProviderError("ESPN: formato inesperado do placar.")
    result = []
    for event in payload["events"]:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competitors = competitions[0].get("competitors", [])
        home = next((row for row in competitors if row.get("homeAway") == "home"), None)
        away = next((row for row in competitors if row.get("homeAway") == "away"), None)
        if home is None or away is None:
            continue
        hc, ac = (team_code(row.get("team", {}).get("abbreviation")) for row in (home, away))
        if not hc or not ac:
            continue
        status = event.get("status") or competitions[0].get("status", {})
        kind = status.get("type", {})
        state = {"pre": "pre", "in": "live", "post": "final"}.get(kind.get("state"), "unavailable")
        if any(word in kind.get("name", "").upper() for word in ("POSTPON", "CANCEL", "SUSPEND")):
            state = "unavailable"
        kickoff = event.get("date")
        if not kickoff:
            continue
        day = _day(kickoff)
        result.append(
            LiveGame(
                str(event["id"]),
                "ESPN",
                day,
                current_season(date.fromisoformat(day)),
                hc,
                ac,
                state,
                now.isoformat(),
                _integer(home.get("score")),
                _integer(away.get("score")),
                int(status.get("period") or 0),
                minutes(status.get("displayClock")),
                kickoff,
                regular_season=event.get("season", payload.get("season", {})).get("type") == 2,
            )
        )
    return result


def attach_espn_box(game: LiveGame, payload: dict, now: datetime | None = None) -> LiveGame:
    header = payload.get("header", {})
    if str(header.get("id")) != game.external_id:
        raise ProviderError("ESPN: identificador divergente no boxscore.")
    status_event = {
        "id": game.external_id,
        "date": game.kickoff,
        "season": {"type": 2 if game.regular_season else 1},
        "competitions": header.get("competitions", []),
    }
    refreshed = parse_espn_board({"events": [status_event]}, now)
    if refreshed:
        game = refreshed[0]
    players = []
    fields = {
        "MIN": "minutes",
        "PTS": "pts",
        "REB": "reb",
        "AST": "ast",
        "OREB": "oreb",
        "DREB": "dreb",
        "STL": "stl",
        "BLK": "blk",
        "TO": "tov",
        "PF": "pf",
    }
    for team in payload.get("boxscore", {}).get("players", []):
        code = team_code(team.get("team", {}).get("abbreviation"))
        if code not in (game.home, game.away):
            raise ProviderError("ESPN: equipe divergente no boxscore.")
        for group in team.get("statistics", []):
            labels = group.get("labels", [])
            for row in group.get("athletes", []):
                athlete = row.get("athlete", {})
                raw = dict(zip(labels, row.get("stats", []), strict=False))
                stats = {key: number(raw.get(label)) for label, key in fields.items() if key != "minutes"}
                for label, made, attempted in (
                    ("FG", "fgm", "fga"),
                    ("3PT", "fg3m", "fg3a"),
                    ("FT", "ftm", "fta"),
                ):
                    parts = str(raw.get(label, "")).split("-")
                    stats[made] = number(parts[0]) if len(parts) == 2 else None
                    stats[attempted] = number(parts[1]) if len(parts) == 2 else None
                players.append(
                    LivePlayer(
                        str(athlete.get("id", "")),
                        str(athlete.get("displayName", "")),
                        code,
                        minutes(raw.get("MIN")),
                        stats,
                        starter=row.get("starter"),
                        ejected=bool(row.get("ejected")),
                    )
                )
    game.players = players
    game.boxscore_at = (now or utc_now()).isoformat()
    return game


def fetch_public_live(client: FeedClient, day: date, provider: str) -> list[LiveGame]:
    if provider == "NBA":
        games = parse_nba_board(client.get("NBA", NBA_BOARD))
    else:
        payload = client.get("ESPN", ESPN_BASE + "/scoreboard", params={"dates": day.strftime("%Y%m%d")})
        games = parse_espn_board(payload)
    games = [game for game in games if game.day == day.isoformat()]
    # Um placar de outra data não é evidência de que hoje não há partidas.
    if provider == "NBA" and not games:
        raise ProviderError("NBA: placar não corresponde à data consultada.")
    for game in games:
        if game.state not in {"live", "final"}:
            continue
        try:
            if provider == "NBA":
                attach_nba_box(game, client.get("NBA", NBA_BOX.format(game_id=game.external_id)))
            else:
                attach_espn_box(
                    game, client.get("ESPN", ESPN_BASE + "/summary", params={"event": game.external_id})
                )
        except ProviderError:
            # O placar pode existir antes das estatísticas individuais. Não as invente.
            game.players = []
            game.boxscore_at = None
    return games
