from __future__ import annotations

import pandas as pd
from nba_api.stats.endpoints import shotchartdetail

from .nba_teams import TEAM_ABBREVIATION_TO_NAME

SOURCE = "nba_api"

_RAW_COLUMNS = [
    "GAME_ID",
    "GAME_EVENT_ID",
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ID",
    "TEAM_NAME",
    "PERIOD",
    "MINUTES_REMAINING",
    "SECONDS_REMAINING",
    "EVENT_TYPE",
    "ACTION_TYPE",
    "SHOT_TYPE",
    "SHOT_ZONE_BASIC",
    "SHOT_ZONE_AREA",
    "SHOT_ZONE_RANGE",
    "SHOT_DISTANCE",
    "LOC_X",
    "LOC_Y",
    "SHOT_ATTEMPTED_FLAG",
    "SHOT_MADE_FLAG",
    "GAME_DATE",
    "HTM",
    "VTM",
]

SHOT_COLUMNS = [
    "player_id",
    "player_name",
    "game_id",
    "game_event_id",
    "season",
    "game_date",
    "team_id",
    "team_name",
    "opponent",
    "period",
    "minutes_remaining",
    "seconds_remaining",
    "event_type",
    "action_type",
    "shot_type",
    "shot_zone_basic",
    "shot_zone_area",
    "shot_zone_range",
    "shot_distance",
    "loc_x",
    "loc_y",
    "loc_x_ft",
    "loc_y_ft",
    "shot_attempted",
    "shot_made",
    "source",
]


def _derive_opponent(team_name: pd.Series, htm: pd.Series, vtm: pd.Series) -> pd.Series:
    """Descobre o adversário comparando o time do arremesso com mandante/visitante.

    HTM/VTM vêm como sigla (ex.: "BOS"); TEAM_NAME do próprio arremesso vem por
    extenso (ex.: "Boston Celtics") — a mesma tradução de sigla já usada para o
    contexto de adversário na página de jogadores (`src/nba_teams.py`).
    """
    home_team_name = htm.map(TEAM_ABBREVIATION_TO_NAME)
    away_team_name = vtm.map(TEAM_ABBREVIATION_TO_NAME)
    is_home = team_name == home_team_name
    return away_team_name.where(is_home, home_team_name)


def normalize_shot_chart(raw: pd.DataFrame, season: str) -> pd.DataFrame:
    """Converte o retorno bruto do `ShotChartDetail` para o formato de `player_shots`.

    Além de renomear colunas para snake_case, normaliza `LOC_X`/`LOC_Y` — que a
    nba_api entrega em unidades de 1/10 de pé, com a cesta na origem — para pés
    de verdade (`loc_x_ft`/`loc_y_ft`), mantendo as colunas originais também.
    """
    data = raw[_RAW_COLUMNS].copy()
    data["GAME_DATE"] = pd.to_datetime(data["GAME_DATE"], format="%Y%m%d")
    data["season"] = season
    data["opponent"] = _derive_opponent(data["TEAM_NAME"], data["HTM"], data["VTM"])
    data["loc_x_ft"] = data["LOC_X"] / 10.0
    data["loc_y_ft"] = data["LOC_Y"] / 10.0
    data["source"] = SOURCE

    data = data.rename(
        columns={
            "GAME_ID": "game_id",
            "GAME_EVENT_ID": "game_event_id",
            "PLAYER_ID": "player_id",
            "PLAYER_NAME": "player_name",
            "TEAM_ID": "team_id",
            "TEAM_NAME": "team_name",
            "PERIOD": "period",
            "MINUTES_REMAINING": "minutes_remaining",
            "SECONDS_REMAINING": "seconds_remaining",
            "EVENT_TYPE": "event_type",
            "ACTION_TYPE": "action_type",
            "SHOT_TYPE": "shot_type",
            "SHOT_ZONE_BASIC": "shot_zone_basic",
            "SHOT_ZONE_AREA": "shot_zone_area",
            "SHOT_ZONE_RANGE": "shot_zone_range",
            "SHOT_DISTANCE": "shot_distance",
            "LOC_X": "loc_x",
            "LOC_Y": "loc_y",
            "SHOT_ATTEMPTED_FLAG": "shot_attempted",
            "SHOT_MADE_FLAG": "shot_made",
            "GAME_DATE": "game_date",
        }
    )
    return data[SHOT_COLUMNS].reset_index(drop=True)


def fetch_player_shots(
    player_id: int,
    season: str,
    season_type: str = "Regular Season",
    team_id: int = 0,
    timeout: int = 60,
) -> pd.DataFrame:
    """Baixa todos os arremessos de um jogador numa temporada (`ShotChartDetail`).

    Uma chamada por jogador por temporada — diferente da coleta de jogos/
    jogadores (uma chamada por temporada inteira para a liga toda), mas do
    mesmo espírito da coleta incremental de Rating oficial e titularidade:
    lenta, feita aos poucos. `team_id=0` não filtra por time, então cobre o
    jogador mesmo que ele tenha trocado de time durante a temporada.
    """
    response = shotchartdetail.ShotChartDetail(
        team_id=team_id,
        player_id=player_id,
        season_nullable=season,
        season_type_all_star=season_type,
        context_measure_simple="FGA",
        timeout=timeout,
    )
    raw = response.shot_chart_detail.get_data_frame()
    return normalize_shot_chart(raw, season)
