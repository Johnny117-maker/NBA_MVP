from __future__ import annotations

import pandas as pd
from nba_api.stats.endpoints import boxscoreadvancedv3, boxscoretraditionalv3, leaguegamelog

TEAM_RAW_COLUMNS = ["GAME_ID", "GAME_DATE", "TEAM_NAME", "MATCHUP", "PTS"]

PLAYER_RAW_COLUMNS = [
    "GAME_ID",
    "GAME_DATE",
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ABBREVIATION",
    "MATCHUP",
    "MIN",
    "PTS",
    "OREB",
    "DREB",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "PF",
    "FGM",
    "FGA",
    "FG3M",
    "FG3A",
    "FTM",
    "FTA",
]

PLAYER_STAT_RENAME = {
    "TEAM_ABBREVIATION": "team",
    "MIN": "minutes",
    "PTS": "pts",
    "OREB": "oreb",
    "DREB": "dreb",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TOV": "tov",
    "PF": "pf",
    "FGM": "fgm",
    "FGA": "fga",
    "FG3M": "fg3m",
    "FG3A": "fg3a",
    "FTM": "ftm",
    "FTA": "fta",
}


def _parse_matchup(matchup: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Extrai adversário e mando de quadra de uma coluna MATCHUP da nba_api.

    MATCHUP vem como "BOS vs. NYK" (mandante) ou "BOS @ NYK" (visitante).
    """
    is_home = matchup.str.contains(" vs. ", regex=False)
    opponent = matchup.str.split(r" vs\. | @ ", regex=True).str[1]
    return opponent, is_home


def fetch_season_games(
    season: str,
    season_type: str = "Regular Season",
    timeout: int = 60,
) -> pd.DataFrame:
    """Baixa o log de jogos de uma temporada (uma linha por time por jogo)."""
    response = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=season_type,
        timeout=timeout,
    )
    raw = response.get_data_frames()[0]
    data = raw[TEAM_RAW_COLUMNS].copy()
    data["GAME_DATE"] = pd.to_datetime(data["GAME_DATE"])
    data["season"] = season
    return data


def pair_home_away(raw: pd.DataFrame) -> pd.DataFrame:
    """Junta as duas linhas (mandante e visitante) de cada GAME_ID em uma partida."""
    is_home = raw["MATCHUP"].str.contains(" vs. ", regex=False)
    is_away = raw["MATCHUP"].str.contains(" @ ", regex=False)

    home = raw.loc[is_home, ["GAME_ID", "GAME_DATE", "season", "TEAM_NAME", "PTS"]].rename(
        columns={"TEAM_NAME": "home_team", "PTS": "home_points"}
    )
    away = raw.loc[is_away, ["GAME_ID", "TEAM_NAME", "PTS"]].rename(
        columns={"TEAM_NAME": "away_team", "PTS": "away_points"}
    )

    games = home.merge(away, on="GAME_ID", how="inner")
    games = games.rename(columns={"GAME_ID": "game_id", "GAME_DATE": "game_date"})
    return (
        games[
            [
                "game_id",
                "game_date",
                "season",
                "home_team",
                "away_team",
                "home_points",
                "away_points",
            ]
        ]
        .sort_values("game_date")
        .reset_index(drop=True)
    )


def fetch_player_season_logs(
    season: str,
    season_type: str = "Regular Season",
    timeout: int = 60,
) -> pd.DataFrame:
    """Baixa o log de jogos de todos os jogadores de uma temporada em uma só chamada."""
    response = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=season_type,
        player_or_team_abbreviation="P",
        timeout=timeout,
    )
    raw = response.get_data_frames()[0]
    data = raw[PLAYER_RAW_COLUMNS].copy()
    data["GAME_DATE"] = pd.to_datetime(data["GAME_DATE"])
    data["season"] = season

    opponent, is_home = _parse_matchup(data["MATCHUP"])
    data["opponent"] = opponent
    data["is_home"] = is_home

    data = data.rename(
        columns={
            "GAME_ID": "game_id",
            "GAME_DATE": "game_date",
            "PLAYER_ID": "player_id",
            "PLAYER_NAME": "player_name",
            **PLAYER_STAT_RENAME,
        }
    )
    data = data.drop(columns=["MATCHUP"])
    data["minutes"] = pd.to_numeric(data["minutes"], errors="coerce").fillna(0.0)

    ordered = [
        "game_id",
        "game_date",
        "season",
        "player_id",
        "player_name",
        "team",
        "opponent",
        "is_home",
        "minutes",
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
    ]
    return data[ordered].sort_values("game_date").reset_index(drop=True)


def fetch_game_advanced_stats(game_id: str, timeout: int = 30) -> pd.DataFrame:
    """Baixa Offensive/Defensive Rating oficiais de um jogo (uma linha por time).

    Usa BoxScoreAdvancedV3: o endpoint mais antigo (BoxScoreAdvancedV2) está
    quebrado na API atual da NBA (resposta sem a chave 'resultSet').
    """
    response = boxscoreadvancedv3.BoxScoreAdvancedV3(game_id=game_id, timeout=timeout)
    team_stats = response.get_data_frames()[1]

    data = pd.DataFrame(
        {
            "game_id": team_stats["gameId"],
            "team": team_stats["teamCity"] + " " + team_stats["teamName"],
            "off_rating": team_stats["offensiveRating"],
            "def_rating": team_stats["defensiveRating"],
            "net_rating": team_stats["netRating"],
            "pace": team_stats["pace"],
        }
    )
    return data


def fetch_game_starters(game_id: str, timeout: int = 30) -> pd.DataFrame:
    """Titularidade (titular/reserva) de cada jogador em um jogo.

    BoxScoreTraditionalV3: o campo `position` vem preenchido (ex.: "F", "G",
    "C") para os 5 titulares de cada time e vazio para o banco — mesmo
    boxscore tradicional, sem custo de chamada extra por temporada. Custa uma
    chamada por jogo, igual ao Rating oficial (`fetch_game_advanced_stats`).
    """
    response = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=timeout)
    player_stats = response.get_data_frames()[0]

    return pd.DataFrame(
        {
            "game_id": player_stats["gameId"],
            "player_id": player_stats["personId"],
            "is_starter": player_stats["position"].str.strip() != "",
        }
    )
