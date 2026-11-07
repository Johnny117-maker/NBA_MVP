import os
import sqlite3
import subprocess
import sys
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from src.live_providers import (
    ApiKeys,
    FeedClient,
    ProviderError,
    attach_espn_box,
    attach_nba_box,
    parse_espn_board,
    parse_nba_board,
)
from src.live_store import (
    acquire_lease,
    cache_get,
    cache_put,
    persist_final,
    read_live_games,
    release_lease,
    reserve_usage,
    save_live_games,
)
from src.live_types import STAT_FIELDS, LiveGame, LivePlayer, current_season, minutes
from src.optional_feeds import fetch_api_sports, fetch_balldontlie, fetch_market_quotes
from src.season_sync import parse_archive
from src.store import count_games, count_player_games, init_db, upsert_games, upsert_player_games


def final_game():
    game = LiveGame(
        "401-test",
        "SportsDataverse/ESPN",
        "2026-10-27",
        "2026-27",
        "BOS",
        "NYK",
        "final",
        datetime.now(UTC).isoformat(),
        70,
        60,
        4,
        0,
    )
    for code, pts, fgm in (("BOS", 14, 7), ("NYK", 12, 6)):
        for i in range(5):
            stats = dict.fromkeys(STAT_FIELDS, 0.0)
            stats.update(pts=pts, fgm=fgm, fga=fgm + 2, reb=4, oreb=1, dreb=3)
            game.players.append(LivePlayer(f"{code}{i}", f"{code} Player {i}", code, 48.0, stats))
    return game


def test_current_season_tracks_year_rollover_and_clock_supports_overtime():
    assert current_season(date(2026, 10, 28)) == "2026-27"
    assert current_season(date(2027, 2, 1)) == "2026-27"
    game = final_game()
    game.period, game.clock_minutes = 5, 2.5
    assert game.elapsed == 50.5
    assert game.remaining == 2.5
    assert minutes("PT11M30.00S") == 11.5
    assert minutes("32:30") == 32.5
    assert minutes(0) == 0
    assert minutes("DNP") is None


def test_final_sync_is_idempotent_and_foreign_ids_are_not_nba_ids(tmp_path):
    path = tmp_path / "nba.db"
    assert persist_final(path, final_game())
    assert count_games(path) == 1
    assert count_player_games(path) == 10
    modified = path.stat().st_mtime_ns
    assert not persist_final(path, final_game())
    assert path.stat().st_mtime_ns == modified
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT MAX(player_id) FROM player_game_stats").fetchone()[0] < 0


@pytest.mark.parametrize("invalid", ["live", "missing_stat", "missing_player", "wrong_score", "preseason"])
def test_partial_or_ineligible_games_never_enter_training_history(tmp_path, invalid):
    game = final_game()
    if invalid == "live":
        game.state = "live"
    elif invalid == "missing_stat":
        game.players[0].stats["ast"] = None
    elif invalid == "missing_player":
        game.players.pop()
    elif invalid == "wrong_score":
        game.home_score = 100
    else:
        game.regular_season = False
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        persist_final(path, game)
    assert not path.exists()


def test_final_corrections_replace_values_without_duplicate_games(tmp_path):
    path = tmp_path / "nba.db"
    persist_final(path, final_game())
    game = final_game()
    game.home_score += 2
    game.players[0].stats["pts"] += 2
    game.players[0].stats["fgm"] += 1
    assert persist_final(path, game)
    assert count_games(path) == 1
    assert count_player_games(path) == 10
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT home_points FROM games").fetchone()[0] == 72


def test_cache_tick_does_not_change_training_database(tmp_path):
    path = tmp_path / "nba.db"
    init_db(path)
    modified = path.stat().st_mtime_ns
    game = final_game()
    # `save_live_games` descarta dias com mais de 7 dias: usar o dia atual evita
    # que o teste passe a falhar conforme a data de execução.
    game.day = datetime.now(UTC).date().isoformat()
    save_live_games(path, [game])
    assert len(read_live_games(path, game.day)) == 1
    cache_put(path, "payload", "test")
    assert cache_get(path, "payload", 60) == "test"
    assert path.stat().st_mtime_ns == modified


def test_shared_lease_and_quota_stop_duplicate_collectors_and_excess_calls(tmp_path):
    path = tmp_path / "nba.db"
    assert acquire_lease(path, "one")
    assert not acquire_lease(path, "two")
    release_lease(path, "two")
    assert not acquire_lease(path, "two")
    release_lease(path, "one")
    assert acquire_lease(path, "two")
    assert reserve_usage(path, "test", {"day": (3, 5), "month": (3, 10)})
    assert not reserve_usage(path, "test", {"day": (3, 5), "month": (3, 10)})
    assert reserve_usage(path, "test", {"day": (2, 5), "month": (2, 10)})


def test_missing_keys_or_free_plan_do_not_request_paid_endpoints(tmp_path, monkeypatch):
    calls = []
    client = FeedClient(tmp_path / "nba.db", ApiKeys(balldontlie="test"))
    monkeypatch.setattr(client, "get", lambda provider, url, **kwargs: calls.append(url) or {"data": []})
    assert fetch_balldontlie(client, date(2026, 10, 28)) == []
    assert calls == ["https://api.balldontlie.io/v1/games"]
    with pytest.raises(ProviderError, match="chave"):
        fetch_market_quotes(client, final_game())
    assert len(calls) == 1
    assert "test" not in repr(client.keys)


def test_provider_errors_do_not_expose_authenticated_url_or_key(tmp_path, monkeypatch):
    import requests

    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("https://example.test?apiKey=PRIVATE-KEY")

    monkeypatch.setattr("src.live_providers.requests.get", unavailable)
    client = FeedClient(tmp_path / "nba.db")
    with pytest.raises(ProviderError) as result:
        client.get("The Odds API", "https://api.the-odds-api.com/test", params={"apiKey": "PRIVATE-KEY"})
    assert "PRIVATE-KEY" not in str(result.value)


def test_public_scoreboards_normalize_states_and_keep_missing_scores_missing():
    nba = parse_nba_board(
        {
            "scoreboard": {
                "gameDate": "2026-10-28",
                "games": [
                    {
                        "gameId": "0022600050",
                        "gameStatus": 2,
                        "period": 3,
                        "gameClock": "PT06M00.00S",
                        "homeTeam": {"teamTricode": "BOS", "score": 70},
                        "awayTeam": {"teamTricode": "NYK", "score": 68},
                    }
                ],
            }
        }
    )[0]
    assert nba.state == "live" and nba.elapsed == 30
    assert nba.regular_season
    espn = parse_espn_board(
        {
            "season": {"type": 2},
            "events": [
                {
                    "id": "espn50",
                    "date": "2026-10-29T00:30Z",
                    "status": {"type": {"state": "pre"}},
                    "competitions": [
                        {
                            "competitors": [
                                {"homeAway": "home", "team": {"abbreviation": "PHO"}},
                                {"homeAway": "away", "team": {"abbreviation": "NY"}},
                            ]
                        }
                    ],
                }
            ],
        }
    )[0]
    assert espn.day == "2026-10-28" and espn.home == "PHX" and espn.away == "NYK"
    assert espn.home_score is None


def test_archive_does_not_import_future_or_preseason_as_results():
    schedule = pd.DataFrame(
        [
            {
                "game_id": "past",
                "game_date": "2026-10-27",
                "home_abbreviation": "BOS",
                "away_abbreviation": "NYK",
                "status_type_state": "post",
                "season_type": "2",
            },
            {
                "game_id": "future",
                "game_date": "2026-10-29",
                "home_abbreviation": "BOS",
                "away_abbreviation": "NYK",
                "status_type_state": "post",
                "season_type": "2",
            },
            {
                "game_id": "preseason",
                "game_date": "2026-10-27",
                "home_abbreviation": "BOS",
                "away_abbreviation": "NYK",
                "status_type_state": "post",
                "season_type": "1",
            },
        ]
    )
    from src.season_sync import ARCHIVE_STATS

    players = pd.DataFrame(
        columns=[
            "game_id",
            "athlete_id",
            "athlete_display_name",
            "team_abbreviation",
            "minutes",
            *ARCHIVE_STATS.values(),
        ]
    )
    games = parse_archive(schedule, players, date(2026, 10, 28))
    assert [game.external_id for game in games] == ["past"]
    assert games[0].archive and not games[0].fresh(datetime.now(UTC))


def test_official_ids_reconcile_foreign_players_and_games_without_losing_history(tmp_path):
    path = tmp_path / "nba.db"
    persist_final(path, final_game())
    official = final_game()
    official.source = "NBA"
    official.external_id = "0022600050"
    for index, player in enumerate(official.players):
        player.external_id = str(100 + index)
    assert persist_final(path, official)
    with sqlite3.connect(path) as connection:
        games = pd.read_sql_query("SELECT * FROM games", connection)
        players = pd.read_sql_query("SELECT * FROM player_game_stats", connection)
    assert len(games) == 1 and len(players) == 10
    assert players["player_id"].min() == 100
    games["game_id"] = official.external_id
    players["game_id"] = official.external_id
    assert upsert_games(games, path) == 0
    assert upsert_player_games(players, path) == 0
    assert count_games(path) == 1 and count_player_games(path) == 10
    # A próxima consulta ao arquivo ESPN reutiliza os IDs oficiais já conciliados.
    assert not persist_final(path, final_game())
    assert count_player_games(path) == 10


def test_authoritative_empty_scoreboard_removes_old_schedule_without_deleting_history(tmp_path):
    path = tmp_path / "nba.db"
    game = final_game()
    persist_final(path, game)
    save_live_games(path, [game])
    save_live_games(path, [], replace_day=game.day)
    assert read_live_games(path, game.day) == []
    assert count_games(path) == 1


def test_dead_collector_does_not_block_restart(tmp_path, monkeypatch):
    path = tmp_path / "nba.db"
    assert acquire_lease(path, "old")
    monkeypatch.setattr("src.live_store._owner_alive", lambda owner: False)
    assert acquire_lease(path, "new")


def test_running_collector_lease_cannot_be_stolen(tmp_path):
    path = tmp_path / "nba.db"
    owner = f"{os.getpid()}:current"
    assert acquire_lease(path, owner)
    assert not acquire_lease(path, "another-collector")
    assert acquire_lease(path, owner)


def test_finished_process_lease_is_reclaimed_without_waiting_for_expiration(tmp_path):
    with subprocess.Popen([sys.executable, "-c", "pass"]) as process:
        process.wait(timeout=10)
        owner = f"{process.pid}:finished"
    path = tmp_path / "nba.db"
    assert acquire_lease(path, owner)
    assert acquire_lease(path, f"{os.getpid()}:replacement")


def test_nba_boxscore_uses_its_own_clock_and_rejects_old_provider_timestamp():
    now = datetime(2026, 10, 28, 22, tzinfo=UTC)
    game = LiveGame(
        "0022600050",
        "NBA",
        "2026-10-28",
        "2026-27",
        "BOS",
        "NYK",
        "live",
        now.isoformat(),
        period=3,
        clock_minutes=6,
    )
    stats = dict.fromkeys(
        (
            "points",
            "reboundsOffensive",
            "reboundsDefensive",
            "reboundsTotal",
            "assists",
            "steals",
            "blocks",
            "turnovers",
            "foulsPersonal",
            "fieldGoalsMade",
            "fieldGoalsAttempted",
            "threePointersMade",
            "threePointersAttempted",
            "freeThrowsMade",
            "freeThrowsAttempted",
        ),
        0,
    )
    stats.update(minutes="PT24M30.00S", points=10, assists=3)
    payload = {
        "meta": {"time": "2026-10-28T21:55:00Z"},
        "game": {
            "gameId": game.external_id,
            "gameStatus": 2,
            "period": 3,
            "gameClock": "PT05M00.00S",
            "homeTeam": {
                "teamTricode": "BOS",
                "score": 80,
                "players": [
                    {"personId": 1, "name": "Player", "statistics": stats, "starter": "1", "oncourt": "1"}
                ],
            },
            "awayTeam": {"teamTricode": "NYK", "score": 78, "players": []},
        },
    }
    result = attach_nba_box(game, payload, now)
    assert result.elapsed == 31 and result.home_score == 80
    assert result.players[0].minutes == 24.5 and result.players[0].stats["ast"] == 3
    assert not result.fresh(now)
    with pytest.raises(ProviderError, match="identificador"):
        attach_nba_box(game, {"game": {"gameId": "other"}}, now)


def test_espn_boxscore_preserves_shooting_counts_and_missing_stats():
    now = datetime(2026, 10, 28, 22, tzinfo=UTC)
    game = LiveGame(
        "espn50",
        "ESPN",
        "2026-10-28",
        "2026-27",
        "BOS",
        "NYK",
        "live",
        now.isoformat(),
        kickoff="2026-10-28T20:00Z",
    )
    payload = {
        "header": {
            "id": "espn50",
            "competitions": [
                {
                    "status": {"type": {"state": "in"}, "period": 3, "displayClock": "06:00"},
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": "BOS"}, "score": "70"},
                        {"homeAway": "away", "team": {"abbreviation": "NY"}, "score": "68"},
                    ],
                }
            ],
        },
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "BOS"},
                    "statistics": [
                        {
                            "labels": ["MIN", "FG", "3PT", "FT", "OREB", "DREB", "REB", "PTS"],
                            "athletes": [
                                {
                                    "athlete": {"id": "50", "displayName": "ESPN Player"},
                                    "stats": ["24:30", "4-7", "1-3", "2-2", "1", "4", "5", "11"],
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }
    result = attach_espn_box(game, payload, now)
    assert result.elapsed == 30 and result.away_score == 68
    athlete = result.players[0]
    assert athlete.stats["fgm"] == 4 and athlete.stats["fg3a"] == 3 and athlete.minutes == 24.5
    assert athlete.stats["ast"] is None


def test_api_sports_includes_next_utc_day_without_changing_nba_game_date(tmp_path, monkeypatch):
    client = FeedClient(tmp_path / "nba.db", ApiKeys(api_sports="test"))
    dates = []

    def response(provider, url, **kwargs):
        dates.append(kwargs["params"]["date"])
        return {
            "response": [
                {
                    "id": 50,
                    "date": {"start": "2026-10-29T02:00Z"},
                    "stage": 2,
                    "status": {"short": 1},
                    "teams": {"home": {"code": "LAL"}, "visitors": {"code": "POR"}},
                    "periods": {"current": 0},
                }
            ]
        }

    monkeypatch.setattr(client, "get", response)
    games = fetch_api_sports(client, date(2026, 10, 28))
    assert dates == ["2026-10-28", "2026-10-29"]
    assert len(games) == 1 and games[0].day == "2026-10-28"
