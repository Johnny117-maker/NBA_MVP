from __future__ import annotations

import numpy as np
import pandas as pd

from .data import team_snapshot
from .model import FEATURE_NAMES, ModelBundle
from .nba_teams import TEAM_CONFERENCE
from .team_strength import current_elo_ratings

DEFAULT_REST_DAYS = 2
DIRECT_PLAYOFF_SEEDS = 6
PLAY_IN_SEEDS = 4  # seeds 7-10


def split_season(
    games: pd.DataFrame, season: str, cutoff_date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa uma temporada em jogos conhecidos (antes do corte) e a simular (depois)."""
    season_games = games[games["season"] == season].sort_values("game_date")
    cutoff = pd.Timestamp(cutoff_date)
    known = season_games[season_games["game_date"] < cutoff].reset_index(drop=True)
    remaining = season_games[season_games["game_date"] >= cutoff].reset_index(drop=True)
    return known, remaining


def current_standings(known_games: pd.DataFrame) -> pd.DataFrame:
    """Vitórias, derrotas e jogos por time a partir dos jogos conhecidos."""
    home = known_games[["home_team", "home_win"]].rename(columns={"home_team": "team"})
    home["win"] = home["home_win"]
    away = known_games[["away_team", "home_win"]].rename(columns={"away_team": "team"})
    away["win"] = 1 - away["home_win"]

    combined = pd.concat([home[["team", "win"]], away[["team", "win"]]], ignore_index=True)
    standings = combined.groupby("team").agg(wins=("win", "sum"), games=("win", "count"))
    standings["losses"] = standings["games"] - standings["wins"]
    return standings.reset_index()


def team_snapshots(known_games: pd.DataFrame, teams: list) -> dict:
    """Um team_snapshot (força congelada no corte) por time."""
    ratings = current_elo_ratings(known_games)
    return {team: team_snapshot(known_games, team, elo_ratings=ratings) for team in teams}


def _matchup_feature_matrix(
    snapshots: dict, home_teams, away_teams, home_rest_days=None, away_rest_days=None
) -> pd.DataFrame:
    """Constrói as mesmas colunas de src.model.FEATURE_NAMES para vários confrontos de uma vez."""
    home_teams = np.asarray(home_teams)
    away_teams = np.asarray(away_teams)
    n = len(home_teams)
    home_rest = np.full(n, DEFAULT_REST_DAYS) if home_rest_days is None else np.asarray(home_rest_days)
    away_rest = np.full(n, DEFAULT_REST_DAYS) if away_rest_days is None else np.asarray(away_rest_days)

    def _get(field):
        return np.array([snapshots[team][field] for team in home_teams]), np.array(
            [snapshots[team][field] for team in away_teams]
        )

    home_net, away_net = _get("net_rating")
    home_form, away_form = _get("win_pct")
    home_elo, away_elo = _get("elo")

    return pd.DataFrame(
        {
            "elo_diff": home_elo - away_elo,
            "net_rating_diff": home_net - away_net,
            "form_diff": home_form - away_form,
            "rest_diff": home_rest - away_rest,
        }
    )[FEATURE_NAMES]


def remaining_game_probabilities(
    bundle: ModelBundle, snapshots: dict, remaining_games: pd.DataFrame
) -> np.ndarray:
    """Probabilidade (mandante vence) de cada jogo restante, calculada uma única vez."""
    if remaining_games.empty:
        return np.array([])
    features = _matchup_feature_matrix(
        snapshots, remaining_games["home_team"], remaining_games["away_team"]
    )
    return bundle.win_model.predict_proba(features)[:, 1]


def simulate_remaining_wins(
    remaining_games: pd.DataFrame,
    probabilities: np.ndarray,
    current_wins: pd.Series,
    teams: list,
    n_simulations: int = 10_000,
    seed: int | None = None,
) -> np.ndarray:
    """Matriz (n_simulations, n_teams) de vitórias finais projetadas."""
    rng = np.random.default_rng(seed)
    team_index = {team: i for i, team in enumerate(teams)}
    n_teams = len(teams)

    final_wins = np.tile(
        np.array([current_wins.get(team, 0) for team in teams], dtype=float),
        (n_simulations, 1),
    )

    if len(remaining_games) == 0:
        return final_wins

    home_wins = rng.random((n_simulations, len(remaining_games))) < probabilities

    home_idx = remaining_games["home_team"].map(team_index).to_numpy()
    away_idx = remaining_games["away_team"].map(team_index).to_numpy()

    home_indicator = np.zeros((len(remaining_games), n_teams))
    home_indicator[np.arange(len(remaining_games)), home_idx] = 1
    away_indicator = np.zeros((len(remaining_games), n_teams))
    away_indicator[np.arange(len(remaining_games)), away_idx] = 1

    final_wins += home_wins.astype(float) @ home_indicator
    final_wins += (~home_wins).astype(float) @ away_indicator
    return final_wins


def _rank_conference(
    final_wins: np.ndarray, teams: list, conference_teams: list, net_ratings: dict
) -> np.ndarray:
    """Índices (em `teams`), por simulação, dos times de uma conferência do 1º ao último seed.

    Totalmente vetorizado (uma chamada cobre todas as simulações de uma vez): o desempate por
    net_rating é embutido em um único score numérico (vitórias pesam muito mais que o desempate),
    para que `argsort` por linha substitua um laço Python por simulação.
    """
    conf_positions = [teams.index(team) for team in conference_teams]
    conf_wins = final_wins[:, conf_positions]  # (n_simulations, n_conference_teams)
    tie_break = np.array([net_ratings[team] for team in conference_teams])

    score = conf_wins * 1000.0 + tie_break[np.newaxis, :]
    order = np.argsort(-score, axis=1)  # (n_simulations, n_conference_teams)
    return np.array(conf_positions)[order]


def simulate_play_in(
    final_wins: np.ndarray,
    teams: list,
    snapshots: dict,
    bundle: ModelBundle,
    seed: int | None = None,
) -> dict:
    """Simula os classificados diretos e o mini-mata-mata do Play-In por conferência."""
    rng = np.random.default_rng(seed)
    n_simulations = final_wins.shape[0]
    net_ratings = {team: snapshots[team]["net_rating"] for team in teams}

    direct_playoffs = np.zeros((n_simulations, len(teams)), dtype=bool)
    play_in_slot = np.zeros((n_simulations, len(teams)), dtype=bool)
    made_playoffs = np.zeros((n_simulations, len(teams)), dtype=bool)

    conferences = sorted({TEAM_CONFERENCE[team] for team in teams if team in TEAM_CONFERENCE})
    for conference in conferences:
        conference_teams = [team for team in teams if TEAM_CONFERENCE.get(team) == conference]
        if len(conference_teams) < DIRECT_PLAYOFF_SEEDS + PLAY_IN_SEEDS:
            continue

        ranked_idx = _rank_conference(
            final_wins, teams, conference_teams, net_ratings
        )  # shape (n_simulations, n_conference_teams), vetorizado

        row_ids = np.arange(n_simulations)
        direct_idx = ranked_idx[:, :DIRECT_PLAYOFF_SEEDS]
        play_in_idx = ranked_idx[:, DIRECT_PLAYOFF_SEEDS : DIRECT_PLAYOFF_SEEDS + PLAY_IN_SEEDS]
        direct_playoffs[row_ids[:, None], direct_idx] = True
        play_in_slot[row_ids[:, None], play_in_idx] = True

        teams_array = np.array(teams)
        seed7 = teams_array[ranked_idx[:, DIRECT_PLAYOFF_SEEDS]]
        seed8 = teams_array[ranked_idx[:, DIRECT_PLAYOFF_SEEDS + 1]]
        seed9 = teams_array[ranked_idx[:, DIRECT_PLAYOFF_SEEDS + 2]]
        seed10 = teams_array[ranked_idx[:, DIRECT_PLAYOFF_SEEDS + 3]]

        # Jogo A: seed7 x seed8 -> vencedor fica com a 7a vaga
        probs_a = bundle.win_model.predict_proba(
            _matchup_feature_matrix(snapshots, seed7, seed8)
        )[:, 1]
        home_wins_a = rng.random(n_simulations) < probs_a
        winner_a = np.where(home_wins_a, seed7, seed8)
        loser_a = np.where(home_wins_a, seed8, seed7)

        # Jogo B: seed9 x seed10 -> perdedor eliminado, vencedor joga o jogo C
        probs_b = bundle.win_model.predict_proba(
            _matchup_feature_matrix(snapshots, seed9, seed10)
        )[:, 1]
        home_wins_b = rng.random(n_simulations) < probs_b
        winner_b = np.where(home_wins_b, seed9, seed10)

        # Jogo C: perdedor de A x vencedor de B -> vencedor fica com a 8a vaga
        probs_c = bundle.win_model.predict_proba(
            _matchup_feature_matrix(snapshots, loser_a, winner_b)
        )[:, 1]
        home_wins_c = rng.random(n_simulations) < probs_c
        winner_c = np.where(home_wins_c, loser_a, winner_b)

        team_index = {team: i for i, team in enumerate(teams)}
        winner_a_idx = pd.Series(winner_a).map(team_index).to_numpy()
        winner_c_idx = pd.Series(winner_c).map(team_index).to_numpy()
        made_playoffs[row_ids, winner_a_idx] = True
        made_playoffs[row_ids, winner_c_idx] = True
        made_playoffs |= direct_playoffs

    return {
        "direct_playoffs": direct_playoffs,
        "play_in_slot": play_in_slot,
        "made_playoffs": made_playoffs,
    }


def actual_final_standings(games: pd.DataFrame, season: str) -> pd.DataFrame:
    """Classificação real da temporada regular (jogos que realmente aconteceram).

    Não inclui os jogos oficiais do Play-In (não são coletados como "Regular
    Season"): o status aqui é apenas a faixa de posição pelo saldo de vitórias
    da temporada regular, não o resultado real do mata-mata do Play-In.
    """
    season_games = games[games["season"] == season]
    standings = current_standings(season_games)
    standings["conference"] = standings["team"].map(TEAM_CONFERENCE)
    standings["seed"] = standings.groupby("conference")["wins"].rank(
        method="first", ascending=False
    ).astype(int)

    def _status(seed: int) -> str:
        if seed <= DIRECT_PLAYOFF_SEEDS:
            return "Classificação direta"
        if seed <= DIRECT_PLAYOFF_SEEDS + PLAY_IN_SEEDS:
            return "Play-In"
        return "Fora"

    standings["status"] = standings["seed"].map(_status)
    return standings.sort_values(["conference", "seed"]).reset_index(drop=True)


def simulate_season(
    games: pd.DataFrame,
    bundle: ModelBundle,
    season: str,
    cutoff_date,
    n_simulations: int = 10_000,
    seed: int | None = None,
) -> pd.DataFrame:
    """Roda a simulação de Monte Carlo completa e devolve um resumo por time."""
    known_games, remaining_games = split_season(games, season, cutoff_date)
    if known_games.empty:
        raise ValueError("Não há jogos conhecidos antes da data de corte escolhida.")

    teams = sorted(set(known_games["home_team"]) | set(known_games["away_team"]))
    standings = current_standings(known_games).set_index("team")
    snapshots = team_snapshots(known_games, teams)

    probabilities = remaining_game_probabilities(bundle, snapshots, remaining_games)
    final_wins = simulate_remaining_wins(
        remaining_games,
        probabilities,
        standings["wins"],
        teams,
        n_simulations=n_simulations,
        seed=seed,
    )
    play_in_result = simulate_play_in(final_wins, teams, snapshots, bundle, seed=seed)

    summary = pd.DataFrame(
        {
            "team": teams,
            "conference": [TEAM_CONFERENCE.get(team, "?") for team in teams],
            "current_wins": [int(standings["wins"].get(team, 0)) for team in teams],
            "projected_wins_mean": final_wins.mean(axis=0),
            "projected_wins_p10": np.percentile(final_wins, 10, axis=0),
            "projected_wins_p90": np.percentile(final_wins, 90, axis=0),
            "prob_direct_playoffs": play_in_result["direct_playoffs"].mean(axis=0),
            "prob_play_in": play_in_result["play_in_slot"].mean(axis=0),
            "prob_playoffs": play_in_result["made_playoffs"].mean(axis=0),
        }
    )
    return summary.sort_values(
        ["conference", "prob_playoffs"], ascending=[True, False]
    ).reset_index(drop=True)
