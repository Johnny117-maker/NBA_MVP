from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from typing import BinaryIO

import numpy as np
import pandas as pd

from .features import engineer_features
from .store import DEFAULT_DB_PATH, read_raw_games, read_team_advanced_stats


REQUIRED_COLUMNS = {
    "game_date",
    "home_team",
    "away_team",
    "home_off_rating",
    "away_off_rating",
    "home_def_rating",
    "away_def_rating",
    "home_net_rating",
    "away_net_rating",
    "home_last10_win_pct",
    "away_last10_win_pct",
    "home_rest_days",
    "away_rest_days",
    "home_points",
    "away_points",
}


@dataclass(frozen=True)
class TeamProfile:
    offense: float
    defense: float
    pace: float
    consistency: float

    @property
    def net_rating(self) -> float:
        return self.offense - self.defense


# Os 30 times reais, com offense/defense calibrados pela média real de pontos
# marcados/sofridos por jogo na temporada 2024-25 (a mais recente encerrada).
# `pace` é uma estimativa a partir da pontuação combinada (não há Rating/pace
# oficial coletado para os 30 times ainda — ver `scripts/update_advanced_stats.py`);
# `consistency` vem do desvio-padrão real do saldo de pontos, mas hoje não é
# usado pelos geradores de jogos sintéticos abaixo. Os jogos em si continuam
# sendo simulados (ruído aleatório), não são o resultado real de 2024-25.
DEMO_TEAMS: dict[str, TeamProfile] = {
    "Atlanta Hawks": TeamProfile(118.4, 119.4, 100.5, 0.76),
    "Boston Celtics": TeamProfile(116.3, 107.2, 98.4, 0.71),
    "Brooklyn Nets": TeamProfile(105.1, 112.2, 97.4, 0.77),
    "Charlotte Hornets": TeamProfile(105.1, 114.2, 97.7, 0.76),
    "Chicago Bulls": TeamProfile(117.8, 119.4, 100.4, 0.66),
    "Cleveland Cavaliers": TeamProfile(121.9, 112.4, 100.0, 0.78),
    "Dallas Mavericks": TeamProfile(114.2, 115.4, 99.3, 0.68),
    "Denver Nuggets": TeamProfile(120.8, 116.9, 100.5, 0.71),
    "Detroit Pistons": TeamProfile(115.5, 113.6, 99.2, 0.75),
    "Golden State Warriors": TeamProfile(113.8, 110.5, 98.5, 0.62),
    "Houston Rockets": TeamProfile(114.5, 109.8, 98.5, 0.75),
    "Indiana Pacers": TeamProfile(117.2, 115.0, 99.7, 0.75),
    "LA Clippers": TeamProfile(112.9, 108.2, 98.0, 0.63),
    "Los Angeles Lakers": TeamProfile(113.4, 112.2, 98.7, 0.68),
    "Memphis Grizzlies": TeamProfile(121.7, 116.9, 100.6, 0.64),
    "Miami Heat": TeamProfile(110.5, 110.2, 98.0, 0.70),
    "Milwaukee Bucks": TeamProfile(115.6, 113.2, 99.2, 0.73),
    "Minnesota Timberwolves": TeamProfile(114.3, 109.3, 98.4, 0.79),
    "New Orleans Pelicans": TeamProfile(109.8, 119.3, 99.2, 0.73),
    "New York Knicks": TeamProfile(115.8, 111.7, 99.0, 0.67),
    "Oklahoma City Thunder": TeamProfile(120.6, 107.8, 99.1, 0.78),
    "Orlando Magic": TeamProfile(105.4, 105.5, 96.5, 0.73),
    "Philadelphia 76ers": TeamProfile(109.6, 115.8, 98.7, 0.80),
    "Phoenix Suns": TeamProfile(113.6, 116.6, 99.4, 0.73),
    "Portland Trail Blazers": TeamProfile(110.9, 113.9, 98.6, 0.60),
    "Sacramento Kings": TeamProfile(115.7, 115.3, 99.5, 0.68),
    "San Antonio Spurs": TeamProfile(113.8, 116.5, 99.4, 0.72),
    "Toronto Raptors": TeamProfile(110.9, 115.2, 98.8, 0.66),
    "Utah Jazz": TeamProfile(111.9, 121.2, 99.8, 0.68),
    "Washington Wizards": TeamProfile(108.1, 120.5, 99.1, 0.75),
}


def generate_demo_games(number_of_games: int = 420, seed: int = 42) -> pd.DataFrame:
    """Gera uma base reprodutível para demonstração e testes do MVP."""
    rng = np.random.default_rng(seed)
    teams = list(DEMO_TEAMS)
    start_date = pd.Timestamp("2023-10-20")
    rows: list[dict[str, object]] = []

    recent_results: dict[str, list[int]] = {team: [] for team in teams}

    for game_number in range(number_of_games):
        home_team, away_team = rng.choice(teams, size=2, replace=False)
        home = DEMO_TEAMS[str(home_team)]
        away = DEMO_TEAMS[str(away_team)]

        home_form = (
            float(np.mean(recent_results[str(home_team)][-10:]))
            if recent_results[str(home_team)]
            else 0.5
        )
        away_form = (
            float(np.mean(recent_results[str(away_team)][-10:]))
            if recent_results[str(away_team)]
            else 0.5
        )

        home_off = home.offense + rng.normal(0, 1.7)
        away_off = away.offense + rng.normal(0, 1.7)
        home_def = home.defense + rng.normal(0, 1.5)
        away_def = away.defense + rng.normal(0, 1.5)
        home_rest = int(rng.choice([1, 2, 3, 4], p=[0.28, 0.46, 0.19, 0.07]))
        away_rest = int(rng.choice([1, 2, 3, 4], p=[0.31, 0.45, 0.18, 0.06]))

        pace_factor = ((home.pace + away.pace) / 2 - 99.0) * 0.32
        home_expected = (
            112.5
            + 0.55 * (home_off - 113.5)
            + 0.42 * (away_def - 113.0)
            + 2.3
            + pace_factor
            + 0.35 * (home_rest - away_rest)
        )
        away_expected = (
            112.5
            + 0.55 * (away_off - 113.5)
            + 0.42 * (home_def - 113.0)
            + pace_factor
            + 0.25 * (away_rest - home_rest)
        )

        home_points = int(round(rng.normal(home_expected, 7.8)))
        away_points = int(round(rng.normal(away_expected, 7.8)))
        if home_points == away_points:
            home_points += int(rng.choice([1, 2, 3]))

        home_win = int(home_points > away_points)
        recent_results[str(home_team)].append(home_win)
        recent_results[str(away_team)].append(1 - home_win)

        rows.append(
            {
                "game_date": start_date.to_pydatetime()
                + timedelta(days=int(game_number // 6)),
                "home_team": str(home_team),
                "away_team": str(away_team),
                "home_off_rating": round(home_off, 2),
                "away_off_rating": round(away_off, 2),
                "home_def_rating": round(home_def, 2),
                "away_def_rating": round(away_def, 2),
                "home_net_rating": round(home_off - home_def, 2),
                "away_net_rating": round(away_off - away_def, 2),
                "home_last10_win_pct": round(home_form, 3),
                "away_last10_win_pct": round(away_form, 3),
                "home_rest_days": home_rest,
                "away_rest_days": away_rest,
                "home_points": home_points,
                "away_points": away_points,
            }
        )

    data = pd.DataFrame(rows).sort_values("game_date").reset_index(drop=True)
    data["home_win"] = (data["home_points"] > data["away_points"]).astype(int)
    return data


def load_games(uploaded_file: BinaryIO | BytesIO | None = None) -> pd.DataFrame:
    """Carrega um CSV do usuário ou retorna a base demonstrativa."""
    if uploaded_file is None:
        return generate_demo_games()

    data = pd.read_csv(uploaded_file)
    missing = REQUIRED_COLUMNS.difference(data.columns)
    if missing:
        columns = ", ".join(sorted(missing))
        raise ValueError(f"O CSV não possui as colunas obrigatórias: {columns}")

    data = data.copy()
    data["game_date"] = pd.to_datetime(data["game_date"], errors="raise")
    numeric_columns = list(REQUIRED_COLUMNS - {"game_date", "home_team", "away_team"})
    data[numeric_columns] = data[numeric_columns].apply(pd.to_numeric, errors="raise")
    data["home_win"] = (data["home_points"] > data["away_points"]).astype(int)
    return data.sort_values("game_date").reset_index(drop=True)


def load_real_games(db_path=DEFAULT_DB_PATH) -> pd.DataFrame:
    """Carrega jogos reais coletados via nba_api e salvos em SQLite.

    Requer que 'python scripts/update_data.py' já tenha sido executado. Usa
    Offensive/Defensive Rating oficiais (`scripts/update_advanced_stats.py`)
    quando disponíveis, com a aproximação por pontos como reserva para os
    jogos ainda não coletados nesse formato.
    """
    raw = read_raw_games(db_path)
    advanced_stats = read_team_advanced_stats(db_path)
    return engineer_features(raw, advanced_stats)


def available_teams(games: pd.DataFrame) -> list[str]:
    home = set(games["home_team"].dropna().astype(str))
    away = set(games["away_team"].dropna().astype(str))
    return sorted(home | away)


def team_game_history(games: pd.DataFrame, team: str) -> pd.DataFrame:
    """Normaliza jogos de um time para uma linha por partida."""
    at_home = games["home_team"].eq(team)
    away = games["away_team"].eq(team)
    selected = games.loc[at_home | away].copy()
    if selected.empty:
        raise ValueError(f"Não há partidas para o time {team}.")

    is_home = selected["home_team"].eq(team)
    history = pd.DataFrame(
        {
            "game_date": selected["game_date"],
            "opponent": np.where(is_home, selected["away_team"], selected["home_team"]),
            "location": np.where(is_home, "Casa", "Fora"),
            "points_for": np.where(is_home, selected["home_points"], selected["away_points"]),
            "points_against": np.where(
                is_home, selected["away_points"], selected["home_points"]
            ),
            "off_rating": np.where(
                is_home, selected["home_off_rating"], selected["away_off_rating"]
            ),
            "def_rating": np.where(
                is_home, selected["home_def_rating"], selected["away_def_rating"]
            ),
            "net_rating": np.where(
                is_home, selected["home_net_rating"], selected["away_net_rating"]
            ),
            "pregame_form": np.where(
                is_home,
                selected["home_last10_win_pct"],
                selected["away_last10_win_pct"],
            ),
        }
    )
    history["win"] = (history["points_for"] > history["points_against"]).astype(int)
    return history.sort_values("game_date").reset_index(drop=True)


def team_snapshot(games: pd.DataFrame, team: str, window: int = 10) -> dict[str, float]:
    history = team_game_history(games, team).tail(window)
    return {
        "off_rating": float(history["off_rating"].mean()),
        "def_rating": float(history["def_rating"].mean()),
        "net_rating": float(history["net_rating"].mean()),
        "win_pct": float(history["win"].mean()),
        "points_for": float(history["points_for"].mean()),
        "points_against": float(history["points_against"].mean()),
        "games": float(len(history)),
    }
