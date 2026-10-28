"""Estimativas experimentais de contagem, condicionadas aos minutos e ao jogo atual."""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from .live_types import LiveGame, LivePlayer, utc_now

PROP_LABELS = {"pts": "Pontos", "reb": "Rebotes", "ast": "Assistências"}


def load_prop_history(db_path: str | Path) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()
    with sqlite3.connect(db_path, timeout=15) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='player_game_stats'").fetchone()
        if not exists:
            return pd.DataFrame()
        rows = pd.read_sql_query(
            "SELECT player_id,player_name,team,game_date,season,minutes,pts,reb,ast "
            "FROM player_game_stats WHERE minutes > 0 ORDER BY game_date DESC,game_id DESC LIMIT 40000",
            connection,
        )
    rows["game_date"] = pd.to_datetime(rows["game_date"])
    return rows.sort_values("game_date")


def player_prior(history: pd.DataFrame, player_id: int, game: LiveGame, stat: str) -> dict | None:
    rows = history.loc[
        history["player_id"].eq(player_id) & history["game_date"].lt(pd.Timestamp(game.day))
    ].tail(40)
    if len(rows) < 3:
        return None
    current = rows.loc[rows["season"].eq(game.season)]
    # Dados antigos não são apresentados como forma da temporada atual.
    if current.empty or (pd.Timestamp(game.day) - current["game_date"].max()).days > 14:
        return None
    recent = current.tail(5)
    previous = rows.loc[~rows["season"].eq(game.season)].tail(10)
    rate_recent = float(recent[stat].sum() / recent["minutes"].sum())
    rate_season = float(current[stat].sum() / current["minutes"].sum())
    expected_minutes = float(0.7 * recent["minutes"].mean() + 0.3 * current["minutes"].mean())
    rate = 0.6 * rate_recent + 0.4 * rate_season
    reference_mean = float(current[stat].mean())
    if not previous.empty:
        weight = min(1.0, len(current) / 5)
        old_rate = float(previous[stat].sum() / previous["minutes"].sum())
        rate = weight * rate + (1 - weight) * old_rate
        reference_mean = weight * reference_mean + (1 - weight) * float(previous[stat].mean())
        expected_minutes = weight * expected_minutes + (1 - weight) * float(previous["minutes"].mean())
    expected_minutes = float(np.clip(expected_minutes, 0, 48))
    rate = max(rate, 0.001)
    mean = rate * expected_minutes
    normalized = rows.tail(20)[stat] / rows.tail(20)["minutes"] * expected_minutes
    variance = max(float(normalized.var(ddof=1)), mean * 1.3, mean + 0.1)
    shape = float(np.clip(mean * mean / (variance - mean), 1.0, 60.0))
    return {
        "rate": rate,
        "minutes": expected_minutes,
        "shape": shape,
        "season_mean": float(current[stat].mean()),
        "reference_mean": reference_mean,
        "recent_mean": float(recent[stat].mean()),
        "season_games": len(current),
        "history_games": len(rows),
        "last_game": current["game_date"].max().date().isoformat(),
    }


def conditional_prop(
    history: pd.DataFrame,
    player: LivePlayer,
    game: LiveGame,
    stat: str,
    line: float,
    now: datetime | None = None,
) -> dict | None:
    if stat not in PROP_LABELS or not math.isfinite(line) or line < 0 or player.canonical_id is None:
        return None
    prior = player_prior(history, player.canonical_id, game, stat)
    if prior is None or not game.regular_season or game.state not in {"pre", "live"}:
        return None
    now = now or utc_now()
    if game.state == "pre":
        kickoff = pd.to_datetime(game.kickoff, utc=True, errors="coerce")
        if pd.isna(kickoff) or kickoff.to_pydatetime() <= now:
            return None
    played = 0.0
    observed = 0
    remaining = prior["minutes"]
    if game.state == "live":
        if not game.fresh(now) or game.elapsed is None or game.remaining is None or game.elapsed <= 0:
            return None
        actual = player.stats.get(stat)
        if (
            actual is None
            or player.minutes is None
            or not math.isfinite(player.minutes)
            or not math.isfinite(float(actual))
            or actual < 0
            or actual != int(actual)
            or player.minutes <= 0
            or player.minutes > game.elapsed + 0.1
        ):
            return None
        played, observed = float(player.minutes), int(actual)
        # Ocupação da quadra: combina rotação recente e utilização nesta partida.
        live_weight = min(0.8, game.elapsed / 48)
        occupation = (1 - live_weight) * prior["minutes"] / 48 + live_weight * played / game.elapsed
        remaining = min(
            game.remaining,
            max(0.0, occupation * game.remaining),
            max(0.0, game.elapsed + game.remaining - played),
        )
        if player.ejected:
            remaining = 0.0
    shape = prior["shape"] + observed
    rate = prior["shape"] / prior["rate"] + played
    if remaining <= 0:
        over, under, push = float(observed > line), float(observed < line), float(observed == line)
        low = high = mean = float(observed)
    else:
        distribution = nbinom(shape, rate / (rate + remaining))
        over = float(distribution.sf(math.floor(line - observed)))
        under = float(distribution.cdf(math.ceil(line - observed) - 1))
        push = max(0.0, 1.0 - over - under)
        mean = observed + float(distribution.mean())
        low, high = (observed + float(distribution.ppf(q)) for q in (0.1, 0.9))
    settled = observed > line or remaining <= 0
    side = "Over" if over >= under else "Under"
    return {
        "player_id": player.canonical_id,
        "player_name": player.name,
        "team": player.team,
        "game_key": game.key,
        "matchup": f"{game.away} @ {game.home}",
        "state": game.state,
        "stat": stat,
        "line": line,
        "over": over,
        "under": under,
        "push": push,
        "side": side,
        "probability": max(over, under),
        "observed": observed,
        "projected": mean,
        "low": low,
        "high": high,
        "remaining_minutes": remaining,
        "eligible": not settled and prior["minutes"] >= 15,
        "confidence": "Amostra curta" if prior["season_games"] < 5 else "Experimental",
        "source": game.source,
        "line_source": "Referência estatística",
        **{
            key: prior[key]
            for key in ("season_mean", "recent_mean", "season_games", "history_games", "last_game")
        },
    }


def players_for_game(history: pd.DataFrame, game: LiveGame) -> list[LivePlayer]:
    if game.state == "live":
        return game.players
    if history.empty:
        return []
    before = history.loc[history["game_date"].lt(pd.Timestamp(game.day))]
    latest = before.sort_values("game_date").groupby("player_id").tail(1)
    latest = latest.loc[latest["team"].isin([game.home, game.away]) & latest["season"].eq(game.season)]
    return [
        LivePlayer(
            str(row["player_id"]),
            row["player_name"],
            row["team"],
            None,
            {},
            canonical_id=int(row["player_id"]),
        )
        for row in latest.to_dict("records")
    ]


def opportunity_candidates(
    history: pd.DataFrame, games: list[LiveGame], now: datetime | None = None
) -> list[dict]:
    if history.empty:
        return []
    now = now or utc_now()
    results = []
    for game in games:
        if game.state not in {"pre", "live"}:
            continue
        if game.state == "pre":
            if not game.kickoff:
                continue
            kickoff = pd.to_datetime(game.kickoff, utc=True, errors="coerce")
            if pd.isna(kickoff) or kickoff.to_pydatetime() <= now:
                continue
        players = players_for_game(history, game)
        for player in players:
            if player.canonical_id is None:
                continue
            for stat in PROP_LABELS:
                prior = player_prior(history, player.canonical_id, game, stat)
                if prior is None or prior["season_mean"] < {"pts": 8, "reb": 2, "ast": 1}[stat]:
                    continue
                if prior["season_games"] < 3:
                    continue
                line = math.floor(prior["reference_mean"]) + 0.5
                row = conditional_prop(history, player, game, stat, line, now)
                if row is not None and row["eligible"]:
                    if prior["season_games"] < 5:
                        row["line_source"] = "Referência com histórico anterior"
                    results.append(row)
    return sorted(results, key=lambda row: (row["state"] == "live", row["probability"]), reverse=True)
