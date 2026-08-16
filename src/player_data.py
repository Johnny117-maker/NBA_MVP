from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .data import DEMO_TEAMS
from .player_metrics import add_advanced_rate_metrics, add_efficiency_metrics, add_per36_rates
from .store import DEFAULT_DB_PATH, read_player_games

# Perfis exclusivamente demonstrativos, não ligados a nenhum jogador real.
ARCHETYPES: dict[str, dict[str, float]] = {
    "Astro": dict(
        minutes=34, fga=18.0, fg_pct=0.49, fg3a=7.0, fg3_pct=0.37, fta=6.5, ft_pct=0.85,
        oreb=1.2, dreb=6.0, ast=6.0, stl=1.1, blk=0.6, tov=3.2, pf=2.0,
    ),
    "Titular": dict(
        minutes=29, fga=12.0, fg_pct=0.46, fg3a=3.5, fg3_pct=0.35, fta=3.0, ft_pct=0.78,
        oreb=1.5, dreb=4.0, ast=3.0, stl=0.9, blk=0.4, tov=1.6, pf=2.2,
    ),
    "Rotacao": dict(
        minutes=20, fga=7.5, fg_pct=0.45, fg3a=2.0, fg3_pct=0.34, fta=1.6, ft_pct=0.75,
        oreb=1.0, dreb=2.5, ast=1.8, stl=0.6, blk=0.3, tov=1.0, pf=1.8,
    ),
    "Banco": dict(
        minutes=12, fga=4.0, fg_pct=0.43, fg3a=1.0, fg3_pct=0.32, fta=0.8, ft_pct=0.72,
        oreb=0.6, dreb=1.4, ast=0.9, stl=0.3, blk=0.2, tov=0.6, pf=1.4,
    ),
}
ROSTER_ARCHETYPES = ["Astro", "Titular", "Titular", "Rotacao", "Banco"]

_FIRST_NAMES = [
    "Andre", "Marco", "Lucas", "Diego", "Kevin", "Tyler", "Miles", "Jordan",
    "Chris", "Devin", "Malik", "Trevor", "Isaiah", "Caleb", "Ethan", "Owen",
    "Noah", "Mason", "Levi", "Cole",
]
_LAST_NAMES = [
    "Silva", "Bennett", "Carter", "Reed", "Foster", "Hayes", "Morgan", "Price",
    "Sanders", "Walsh", "Nolan", "Griffin", "Doyle", "Kessler", "Vance",
    "Whitman", "Ortiz", "Blake", "Sawyer", "Prescott",
]


def _generate_roster(seed: int) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    combos = [(first, last) for first in _FIRST_NAMES for last in _LAST_NAMES]
    teams = list(DEMO_TEAMS)
    picks = rng.permutation(len(combos))[: len(teams) * len(ROSTER_ARCHETYPES)]

    roster = []
    player_id = 1
    pick_index = 0
    for team in teams:
        for archetype in ROSTER_ARCHETYPES:
            first, last = combos[picks[pick_index]]
            roster.append(
                {
                    "player_id": player_id,
                    "player_name": f"{first} {last}",
                    "team": team,
                    "archetype": archetype,
                }
            )
            player_id += 1
            pick_index += 1
    return roster


def _sample_game_stats(rng: np.random.Generator, profile: dict[str, float]) -> dict[str, object]:
    minutes = max(0.0, rng.normal(profile["minutes"], 4.5))
    fga = max(0, int(round(rng.normal(profile["fga"], 2.5))))
    fg3a = min(fga, max(0, int(round(rng.normal(profile["fg3a"], 1.2)))))
    fta = max(0, int(round(rng.normal(profile["fta"], 1.5))))

    fg_pct = float(np.clip(rng.normal(profile["fg_pct"], 0.06), 0.25, 0.75))
    fg3_pct = float(np.clip(rng.normal(profile["fg3_pct"], 0.08), 0.0, 0.6))
    ft_pct = float(np.clip(rng.normal(profile["ft_pct"], 0.07), 0.4, 1.0))

    fg3m = min(fg3a, max(0, int(round(fg3a * fg3_pct))))
    two_point_attempts = fga - fg3a
    two_point_made = max(0, int(round(two_point_attempts * fg_pct)))
    fgm = min(fga, fg3m + two_point_made)
    ftm = min(fta, max(0, int(round(fta * ft_pct))))

    points = 2 * (fgm - fg3m) + 3 * fg3m + ftm
    oreb = max(0, int(round(rng.normal(profile["oreb"], 0.8))))
    dreb = max(0, int(round(rng.normal(profile["dreb"], 1.5))))

    return {
        "minutes": round(minutes, 1),
        "pts": points,
        "oreb": oreb,
        "dreb": dreb,
        "reb": oreb + dreb,
        "ast": max(0, int(round(rng.normal(profile["ast"], 1.8)))),
        "stl": max(0, int(round(rng.normal(profile["stl"], 0.7)))),
        "blk": max(0, int(round(rng.normal(profile["blk"], 0.5)))),
        "tov": max(0, int(round(rng.normal(profile["tov"], 1.0)))),
        "pf": max(0, int(round(rng.normal(profile["pf"], 0.9)))),
        "fgm": fgm,
        "fga": fga,
        "fg3m": fg3m,
        "fg3a": fg3a,
        "ftm": ftm,
        "fta": fta,
    }


def generate_demo_player_games(games_per_team: int = 40, seed: int = 7) -> pd.DataFrame:
    """Gera um boxscore sintético e reprodutível de jogadores para demonstração e testes."""
    roster = _generate_roster(seed)
    rng = np.random.default_rng(seed + 1)
    teams = list(DEMO_TEAMS)
    start_date = pd.Timestamp("2023-10-20")

    roster_by_team = {team: [player for player in roster if player["team"] == team] for team in teams}

    rows = []
    game_counter = 0
    for team in teams:
        opponents = rng.choice(
            [other for other in teams if other != team], size=games_per_team
        )
        for game_number in range(games_per_team):
            opponent = opponents[game_number]
            game_id = f"DEMO-{game_counter:05d}"
            game_counter += 1
            game_date = start_date + timedelta(days=game_number * 2)
            is_home = bool(rng.integers(0, 2))

            # Ambos os times entram no boxscore do mesmo jogo, como na coleta real.
            for side_team, side_opponent, side_is_home in (
                (team, opponent, is_home),
                (opponent, team, not is_home),
            ):
                for player in roster_by_team[side_team]:
                    profile = ARCHETYPES[player["archetype"]]
                    stats = _sample_game_stats(rng, profile)
                    rows.append(
                        {
                            "game_id": game_id,
                            "game_date": game_date,
                            "season": "DEMO",
                            "player_id": player["player_id"],
                            "player_name": player["player_name"],
                            "team": side_team,
                            "opponent": side_opponent,
                            "is_home": side_is_home,
                            **stats,
                        }
                    )

    return pd.DataFrame(rows).sort_values("game_date").reset_index(drop=True)


def load_player_games(source: str = "demo", db_path=DEFAULT_DB_PATH) -> pd.DataFrame:
    """Carrega estatísticas de jogadores (demo ou reais) já com eficiência e per-36 calculados."""
    if source == "demo":
        raw = generate_demo_player_games()
    elif source == "real":
        raw = read_player_games(db_path)
    else:
        raise ValueError(f"Fonte desconhecida: {source!r}. Use 'demo' ou 'real'.")

    with_efficiency = add_efficiency_metrics(raw)
    with_rates = add_per36_rates(with_efficiency)
    return add_advanced_rate_metrics(with_rates)
