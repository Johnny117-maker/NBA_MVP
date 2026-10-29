"""Sincronização incremental da temporada e monitor independente das sessões do navegador."""

from __future__ import annotations

import atexit
import logging
import os
import threading
import uuid
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .live_providers import ApiKeys, FeedClient, ProviderError, fetch_public_live, team_code
from .live_store import (
    acquire_lease,
    clear_archive_cache,
    get_state,
    normalized_name,
    persist_final,
    player_identity_index,
    read_live_games,
    release_lease,
    resolve_player,
    save_live_games,
    set_state,
)
from .live_types import EASTERN, LiveGame, LivePlayer, current_season, minutes, number, utc_now
from .optional_feeds import fetch_api_sports, fetch_balldontlie
from .store import init_db

ARCHIVE_STATS = {
    "pts": "points",
    "oreb": "offensive_rebounds",
    "dreb": "defensive_rebounds",
    "reb": "rebounds",
    "ast": "assists",
    "stl": "steals",
    "blk": "blocks",
    "tov": "turnovers",
    "pf": "fouls",
    "fgm": "field_goals_made",
    "fga": "field_goals_attempted",
    "fg3m": "three_point_field_goals_made",
    "fg3a": "three_point_field_goals_attempted",
    "ftm": "free_throws_made",
    "fta": "free_throws_attempted",
}


def parse_archive(schedule: pd.DataFrame, player_rows: pd.DataFrame, day: date) -> list[LiveGame]:
    schedule_required = {
        "game_id",
        "game_date",
        "home_abbreviation",
        "away_abbreviation",
        "status_type_state",
        "season_type",
    }
    player_required = {
        "game_id",
        "athlete_id",
        "athlete_display_name",
        "team_abbreviation",
        "minutes",
        *ARCHIVE_STATS.values(),
    }
    if not schedule_required.issubset(schedule) or not player_required.issubset(player_rows):
        raise ProviderError("SportsDataverse/ESPN: colunas obrigatórias ausentes no arquivo.")
    season = current_season(day)
    dates = pd.to_datetime(schedule["game_date"], errors="coerce").dt.date
    selected = schedule.loc[schedule["season_type"].astype(str).eq("2") & dates.notna()].copy()
    selected = selected.loc[
        dates.loc[selected.index].between(date(int(season[:4]), 9, 1), day + timedelta(days=1))
    ]
    grouped = {str(gid): frame for gid, frame in player_rows.groupby("game_id", sort=False)}
    fetched = utc_now().isoformat()
    result = []
    for row in selected.to_dict("records"):
        home, away = team_code(row["home_abbreviation"]), team_code(row["away_abbreviation"])
        if not home or not away:
            continue
        game_day = str(row["game_date"])[:10]
        state = {"pre": "pre", "in": "live", "post": "final"}.get(
            str(row["status_type_state"]), "unavailable"
        )
        if any(
            word in str(row.get("status_type_name", "")).upper() for word in ("POSTPON", "CANCEL", "SUSPEND")
        ):
            state = "unavailable"
        if state == "final" and game_day > day.isoformat():
            continue
        home_score, away_score = number(row.get("home_score")), number(row.get("away_score"))
        game = LiveGame(
            str(row["game_id"]),
            "SportsDataverse/ESPN",
            game_day,
            season,
            home,
            away,
            state,
            fetched,
            None if home_score is None else int(home_score),
            None if away_score is None else int(away_score),
            int(number(row.get("status_period")) or 0),
            minutes(row.get("status_display_clock")),
            str(row.get("date") or "") or None,
            archive=True,
        )
        rows = grouped.get(game.external_id, pd.DataFrame())
        for athlete in rows.to_dict("records"):
            code = team_code(athlete["team_abbreviation"])
            if code not in (home, away):
                continue
            starter = str(athlete.get("starter", "")).lower()
            game.players.append(
                LivePlayer(
                    str(athlete["athlete_id"]),
                    str(athlete["athlete_display_name"]),
                    code,
                    minutes(athlete.get("minutes")),
                    {key: number(athlete.get(value)) for key, value in ARCHIVE_STATS.items()},
                    starter=None if starter not in {"true", "false"} else starter == "true",
                    ejected=str(athlete.get("ejected", "")).lower() == "true",
                )
            )
        result.append(game)
    return result


def parse_crosswalk(frame: pd.DataFrame) -> dict[str, int]:
    required = {"espn_athlete_id", "espn_full_name", "nba_player_id", "nba_player_name"}
    if not required.issubset(frame):
        return {}
    result = {}
    for row in frame.to_dict("records"):
        pid = number(row["nba_player_id"])
        if (
            pid is not None
            and pid > 0
            and normalized_name(str(row["espn_full_name"])) == normalized_name(str(row["nba_player_name"]))
        ):
            result[str(row["espn_athlete_id"])] = int(pid)
    return result


class SeasonSync:
    def __init__(self, db_path: str | Path, keys: ApiKeys | None = None, *, archive_analysis: bool = True):
        self.db_path = Path(db_path).resolve()
        self.client = FeedClient(self.db_path, keys)
        self.archive_analysis = archive_analysis
        self.owner = f"{os.getpid()}:{uuid.uuid4().hex}"
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.refresh_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.crosswalk: dict[str, int] = {}

    def start(self) -> SeasonSync:
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._watch, name="nba-season-sync", daemon=True)
            self.thread.start()
            from .history_sources import start_current_history_sync

            start_current_history_sync(self.db_path, self.stop_event)
            from .injuries import start_injury_sync

            start_injury_sync(self.db_path, self.stop_event)
            from .remote_archive import start_remote_archive_sync

            start_remote_archive_sync(self.db_path, self.stop_event)
            atexit.register(self.stop)
        return self

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def request_refresh(self) -> None:
        self.refresh_event.set()
        self.wake_event.set()

    def _watch(self) -> None:
        while not self.stop_event.is_set():
            interval = 30
            try:
                result = self.run_once()
                interval = int(result.get("next_poll_seconds", 30))
            except Exception:
                # O monitor continua vivo após falhas de rede, formato ou bloqueio temporário do SQLite.
                logging.getLogger(__name__).exception("Falha na sincronização automática NBA")
            self.wake_event.wait(interval)
            self.wake_event.clear()

    def run_once(self, day: date | None = None) -> dict:
        day = day or utc_now().astimezone(EASTERN).date()
        if not acquire_lease(self.db_path, self.owner):
            return {"status": "Outro monitor já está atualizando esta base."}
        try:
            return self._run_locked(day)
        finally:
            release_lease(self.db_path, self.owner)

    def _run_locked(self, day: date) -> dict:
        init_db(self.db_path)
        now = utc_now()
        if self.refresh_event.is_set():
            self.refresh_event.clear()
            last_manual = get_state(self.db_path, "last_manual_refresh", 0)
            if now.timestamp() - last_manual >= 60:
                clear_archive_cache(self.db_path)
                set_state(self.db_path, "archive_next", 0)
                set_state(self.db_path, "last_manual_refresh", now.timestamp())
        status = get_state(self.db_path, "status", {})
        status.update({"checked_at": now.isoformat(), "season": current_season(day), "errors": []})
        names = player_identity_index(self.db_path)
        changed = 0
        rejected = []
        archive_due = get_state(self.db_path, "archive_next", 0)
        if now.timestamp() >= archive_due:
            try:
                year = int(current_season(day)[:4]) + 1
                schedule = self.client.archive("schedule", year)
                players = self.client.archive("players", year)
                try:
                    self.crosswalk = parse_crosswalk(self.client.archive("crosswalk", year))
                except ProviderError:
                    self.crosswalk = {}
                games = parse_archive(schedule, players, day)
                for game in games:
                    if game.state == "final":
                        try:
                            changed += int(persist_final(self.db_path, game, self.crosswalk, names))
                        except ValueError as error:
                            rejected.append(f"{game.external_id}: {error}")
                save_live_games(
                    self.db_path, [g for g in games if g.day >= (day - timedelta(days=1)).isoformat()]
                )
                status["archive_success_at"] = now.isoformat()
                status["archive_latest_game"] = max(
                    (g.day for g in games if g.state == "final"), default=None
                )
                set_state(self.db_path, "archive_next", now.timestamp() + 3600)
            except (ProviderError, ValueError) as error:
                status["errors"].append(str(error))
                set_state(self.db_path, "archive_next", now.timestamp() + 300)

        days = [day]
        previous = read_live_games(self.db_path, (day - timedelta(days=1)).isoformat())
        if any(g.state in {"live", "pre"} and g.kickoff for g in previous):
            days.append(day - timedelta(days=1))
        live_ok = False
        providers = ["NBA", "ESPN"]
        if self.client.keys.api_sports or self.client.keys.rapidapi:
            providers.append("API-Sports")
        if self.client.keys.balldontlie:
            providers.append("balldontlie")
        for selected_day in days:
            for provider in providers:
                cooldown = get_state(self.db_path, "cooldown:" + provider, 0)
                if now.timestamp() < cooldown:
                    continue
                try:
                    if provider == "API-Sports":
                        games = fetch_api_sports(self.client, selected_day)
                    elif provider == "balldontlie":
                        games = fetch_balldontlie(self.client, selected_day)
                    else:
                        games = fetch_public_live(self.client, selected_day, provider)
                    for game in games:
                        for player in game.players:
                            player.canonical_id = resolve_player(
                                self.db_path, game.source, player, self.crosswalk, names
                            )
                        if game.state == "final" and game.players:
                            try:
                                changed += int(persist_final(self.db_path, game, self.crosswalk, names))
                            except ValueError as error:
                                rejected.append(f"{game.external_id}: {error}")
                    save_live_games(self.db_path, games, replace_day=selected_day.isoformat())
                    status["live_success_at"] = utc_now().isoformat()
                    status["live_source"] = provider
                    live_ok = True
                    break
                except (ProviderError, ValueError, KeyError) as error:
                    status["errors"].append(str(error))
                    set_state(self.db_path, "cooldown:" + provider, now.timestamp() + 300)
        status["live_available"] = live_ok
        tracked = read_live_games(self.db_path, day.isoformat()) + previous
        active = any(g.state == "live" and not g.archive for g in tracked)
        approaching = any(
            g.state == "pre"
            and g.kickoff
            and -14400
            <= (pd.to_datetime(g.kickoff, utc=True) - pd.Timestamp(utc_now())).total_seconds()
            <= 7200
            for g in tracked
        )
        status["next_poll_seconds"] = 30 if active else 60 if approaching else 300
        if status["errors"]:
            status["last_errors"] = status["errors"]
        elif not live_ok:
            status["errors"] = status.get("last_errors", [])
        status["changed_games"] = changed
        status["rejected_games"] = rejected[:10]
        if not self.archive_analysis:
            set_state(self.db_path, "status", status)
            return status
        try:
            from .analysis_archive import run_daily_analysis
            from .research_feeds import collect_rim_daily

            status["daily_analysis"] = run_daily_analysis(self.db_path)
            if os.environ.get("NBA_AUTO_SYNC", "1") != "0":
                status["rim_defense"] = collect_rim_daily(self.db_path, day)
        except Exception as error:
            logging.getLogger(__name__).exception("Falha no arquivo de análises pré-jogo")
            status["daily_analysis"] = {"error": str(error)}
        set_state(self.db_path, "status", status)
        return status
