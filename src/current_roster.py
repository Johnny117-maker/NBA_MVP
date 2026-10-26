from __future__ import annotations

from datetime import date

import pandas as pd


def current_nba_season() -> str:
    """Retorna a temporada atual da NBA no formato YYYY-YY."""
    today = date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fetch_current_roster() -> pd.DataFrame:
    """
    Busca o elenco atual da NBA.

    Retorna as colunas player_id, player_name e team.
    Não altera nem substitui os registros históricos de partidas.
    """
    from nba_api.stats.endpoints import commonallplayers

    season = current_nba_season()
    endpoint = commonallplayers.CommonAllPlayers(
        is_only_current_season=1,
        league_id="00",
        season=season,
        timeout=30,
    )

    frames = endpoint.get_data_frames()
    if not frames:
        raise ValueError("A API da NBA não retornou dados do elenco.")

    roster = frames[0].copy()

    required = {"PERSON_ID", "TEAM_ABBREVIATION"}
    if not required.issubset(roster.columns):
        raise ValueError(
            f"Resposta da API sem as colunas necessárias: {required}"
        )

    name_column = (
        "DISPLAY_FIRST_LAST"
        if "DISPLAY_FIRST_LAST" in roster.columns
        else "DISPLAY_LAST_COMMA_FIRST"
    )

    roster = roster.rename(
        columns={
            "PERSON_ID": "player_id",
            name_column: "player_name",
            "TEAM_ABBREVIATION": "team",
        }
    )

    # Ignora jogadores sem equipe atribuída no elenco atual.
    roster["player_id"] = pd.to_numeric(
        roster["player_id"], errors="coerce"
    )
    roster["team"] = roster["team"].fillna("").astype(str).str.strip().str.upper()
    roster = roster[
        roster["player_id"].notna() & roster["team"].ne("")
    ].copy()

    roster["player_id"] = roster["player_id"].astype(int)
    roster["player_name"] = roster["player_name"].fillna("").astype(str)

    roster = roster[["player_id", "player_name", "team"]]
    roster = roster.drop_duplicates(subset=["player_id"], keep="last")

    if len(roster) < 300:
        raise ValueError(
            f"Elenco recebido parece incompleto ({len(roster)} jogadores)."
        )

    return roster.reset_index(drop=True)
