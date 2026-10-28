"""Fontes autenticadas opcionais; fontes públicas continuam sendo o padrão."""

from __future__ import annotations

from datetime import date, timedelta

from .live_providers import FeedClient, ProviderError, _day, team_code
from .live_store import normalized_name
from .live_types import STAT_FIELDS, LiveGame, LivePlayer, current_season, minutes, number, utc_now


def fetch_api_sports(client: FeedClient, day: date) -> list[LiveGame]:
    if client.keys.api_sports:
        base = "https://v2.nba.api-sports.io"
        headers = {"x-apisports-key": client.keys.api_sports}
    elif client.keys.rapidapi:
        base = "https://api-nba-v1.p.rapidapi.com"
        headers = {"x-rapidapi-key": client.keys.rapidapi, "x-rapidapi-host": "api-nba-v1.p.rapidapi.com"}
    else:
        raise ProviderError("API-Sports: chave não configurada.")
    rows = []
    for utc_day in (day, day + timedelta(days=1)):
        payload = client.get(
            "API-Sports", base + "/games", params={"date": utc_day.isoformat()}, headers=headers, ttl=900
        )
        if not isinstance(payload.get("response"), list):
            raise ProviderError("API-Sports: formato inesperado do placar.")
        rows.extend(payload["response"])
    result = []
    seen = set()
    for row in rows:
        kickoff = row.get("date", {}).get("start")
        if not kickoff or _day(kickoff) != day.isoformat() or row.get("id") in seen:
            continue
        seen.add(row.get("id"))
        teams, scores = row.get("teams", {}), row.get("scores", {})
        hc, ac = (
            team_code(teams.get(side, {}).get("code") or teams.get(side, {}).get("name"))
            for side in ("home", "visitors")
        )
        if not hc or not ac:
            continue
        state = {1: "pre", 2: "live", 3: "final"}.get(
            int(row.get("status", {}).get("short") or 0), "unavailable"
        )
        home, away = (number(scores.get(side, {}).get("points")) for side in ("home", "visitors"))
        game = LiveGame(
            str(row.get("id", "")),
            "API-Sports",
            day.isoformat(),
            current_season(day),
            hc,
            ac,
            state,
            utc_now().isoformat(),
            None if home is None else int(home),
            None if away is None else int(away),
            int(row.get("periods", {}).get("current") or 0),
            minutes(row.get("status", {}).get("clock", row.get("clock"))),
            row.get("date", {}).get("start"),
            regular_season=int(row.get("stage") or 0) == 2,
        )
        if state in {"live", "final"}:
            try:
                box = client.get(
                    "API-Sports",
                    base + "/players/statistics",
                    headers=headers,
                    params={"game": game.external_id},
                    ttl=900,
                )
                for athlete in box.get("response", []):
                    person = athlete.get("player", {})
                    code = team_code(
                        athlete.get("team", {}).get("code") or athlete.get("team", {}).get("name")
                    )
                    if code not in (hc, ac) or str(athlete.get("game", {}).get("id")) != game.external_id:
                        continue
                    mapping = {
                        "pts": "points",
                        "oreb": "offReb",
                        "dreb": "defReb",
                        "reb": "totReb",
                        "ast": "assists",
                        "stl": "steals",
                        "blk": "blocks",
                        "tov": "turnovers",
                        "pf": "pFouls",
                        "fgm": "fgm",
                        "fga": "fga",
                        "fg3m": "tpm",
                        "fg3a": "tpa",
                        "ftm": "ftm",
                        "fta": "fta",
                    }
                    game.players.append(
                        LivePlayer(
                            str(person.get("id", "")),
                            f"{person.get('firstname', '')} {person.get('lastname', '')}".strip(),
                            code,
                            minutes(athlete.get("min")),
                            {key: number(athlete.get(value)) for key, value in mapping.items()},
                        )
                    )
                if game.players:
                    # O cache de 15 minutos protege as 100 chamadas/dia; não é um feed de baixa latência.
                    game.boxscore_at = None
            except ProviderError:
                pass
        result.append(game)
    return result


def fetch_balldontlie(client: FeedClient, day: date) -> list[LiveGame]:
    if not client.keys.balldontlie:
        raise ProviderError("balldontlie: chave não configurada.")
    headers = {"Authorization": client.keys.balldontlie}
    payload = client.get(
        "balldontlie",
        "https://api.balldontlie.io/v1/games",
        params={"dates[]": day.isoformat(), "per_page": 100},
        headers=headers,
        ttl=60,
    )
    if not isinstance(payload.get("data"), list):
        raise ProviderError("balldontlie: formato inesperado do placar.")
    games = []
    for row in payload["data"]:
        home, away = row.get("home_team", {}), row.get("visitor_team", {})
        hc, ac = team_code(home.get("abbreviation")), team_code(away.get("abbreviation"))
        if not hc or not ac or str(row.get("date", ""))[:10] != day.isoformat():
            continue
        period, status = int(row.get("period") or 0), str(row.get("status", "")).lower()
        state = "final" if "final" in status else "live" if period > 0 else "pre"
        if any(word in status for word in ("postpon", "cancel", "suspend")):
            state = "unavailable"
        games.append(
            LiveGame(
                str(row["id"]),
                "balldontlie",
                day.isoformat(),
                current_season(day),
                hc,
                ac,
                state,
                utc_now().isoformat(),
                row.get("home_team_score"),
                row.get("visitor_team_score"),
                period,
                minutes(row.get("time")),
                row.get("datetime"),
                regular_season=not bool(row.get("postseason")),
            )
        )
    # O plano grátis não inclui estatísticas de jogadores nem boxscores.
    if client.keys.bdl_plan.lower() not in {"goat", "all-access"}:
        return games
    box = client.get(
        "balldontlie",
        "https://api.balldontlie.io/v1/box_scores",
        params={"date": day.isoformat()},
        headers=headers,
        ttl=30,
    )
    for row in box.get("data", []):
        hc = team_code(row.get("home_team", {}).get("abbreviation"))
        ac = team_code(row.get("visitor_team", {}).get("abbreviation"))
        game = next((game for game in games if game.home == hc and game.away == ac), None)
        if game is None:
            continue
        for side, code in (("home_team", hc), ("visitor_team", ac)):
            for raw in row.get(side, {}).get("players", []):
                player = raw.get("player", {})
                game.players.append(
                    LivePlayer(
                        str(player.get("id", "")),
                        f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
                        code,
                        minutes(raw.get("min")),
                        {key: number(raw.get(key)) for key in STAT_FIELDS},
                    )
                )
        # Um resumo pode estar atrasado em relação ao placar. Somente o payload
        # com período, relógio e placar próprios é usado para condicionar projeções.
        if game.players and row.get("period") is not None and row.get("time") is not None:
            game.period = int(row["period"])
            game.clock_minutes = minutes(row["time"])
            game.home_score = row.get("home_team_score")
            game.away_score = row.get("visitor_team_score")
            game.boxscore_at = utc_now().isoformat()
    return games


def fetch_market_quotes(client: FeedClient, game: LiveGame) -> list[dict]:
    if not client.keys.odds:
        raise ProviderError("The Odds API: chave não configurada.")
    base = "https://api.the-odds-api.com/v4/sports/basketball_nba"
    events = client.get("The Odds API", base + "/events", params={"apiKey": client.keys.odds}, ttl=3600)
    event = next(
        (
            item
            for item in events
            if team_code(item.get("home_team")) == game.home
            and team_code(item.get("away_team")) == game.away
            and str(item.get("commence_time", ""))[:10] in {game.day, str(game.kickoff or "")[:10]}
        ),
        None,
    )
    if event is None:
        raise ProviderError("The Odds API: confronto não encontrado.")
    payload = client.get(
        "The Odds API",
        f"{base}/events/{event['id']}/odds",
        cost=3,
        params={
            "apiKey": client.keys.odds,
            "regions": "us",
            "oddsFormat": "decimal",
            "markets": "player_points,player_rebounds,player_assists",
        },
        ttl=60 if game.state == "live" else 600,
    )
    results = []
    for book in payload.get("bookmakers", []):
        for market in book.get("markets", []):
            stat = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast"}.get(
                market.get("key")
            )
            if stat is None:
                continue
            for outcome in market.get("outcomes", []):
                line, price = number(outcome.get("point")), number(outcome.get("price"))
                if (
                    line is None
                    or price is None
                    or price <= 1
                    or outcome.get("name") not in {"Over", "Under"}
                ):
                    continue
                results.append(
                    {
                        "player_name": outcome.get("description", ""),
                        "name_key": normalized_name(outcome.get("description", "")),
                        "stat": stat,
                        "line": line,
                        "side": outcome["name"],
                        "price": price,
                        "bookmaker": book.get("title", book.get("key", "")),
                        "updated_at": market.get("last_update") or book.get("last_update"),
                        "source": "The Odds API",
                    }
                )
    return results
