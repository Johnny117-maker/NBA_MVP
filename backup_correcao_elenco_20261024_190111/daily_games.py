from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

from .nba_teams import TEAM_ABBREVIATION_TO_NAME

EASTERN = ZoneInfo("America/New_York")
BRASILIA = ZoneInfo("America/Sao_Paulo")


def today_et() -> date:
    """Data atual do calendário NBA, usando o fuso da costa leste dos EUA."""
    from datetime import datetime
    return datetime.now(EASTERN).date()


def team_aliases(team: str) -> set[str]:
    """Retorna sigla e nome oficial de um time, aceitando qualquer capitalização."""
    raw = str(team or "").strip()
    if not raw:
        return set()
    upper = raw.upper()
    if upper in TEAM_ABBREVIATION_TO_NAME:
        return {upper, TEAM_ABBREVIATION_TO_NAME[upper]}
    for code, name in TEAM_ABBREVIATION_TO_NAME.items():
        if raw.casefold() in {name.casefold(), code.casefold()}:
            return {code, name}
    return {raw}


def build_form_table(player_games: pd.DataFrame) -> pd.DataFrame:
    """Resume forma recente e temporada mais recente para cada jogador."""
    columns = ["player_id", "player_name", "team", "minutes_recent", "pts_recent", "reb_recent",
               "ast_recent", "pts_season", "pts_delta", "last_game_date", "impact_recent"]
    if player_games is None or player_games.empty:
        return pd.DataFrame(columns=columns)
    required = {"player_id", "player_name", "team", "game_date", "minutes", "pts", "reb", "ast"}
    if not required.issubset(player_games.columns):
        return pd.DataFrame(columns=columns)
    data = player_games.copy()
    data["game_date"] = pd.to_datetime(data["game_date"], errors="coerce")
    for col in ("minutes", "pts", "reb", "ast"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["player_id", "game_date"]).sort_values("game_date")
    if data.empty:
        return pd.DataFrame(columns=columns)
    result = []
    league_latest_date = data["game_date"].max().normalize()
    for player_id, group in data.groupby("player_id", sort=False):
        group = group.sort_values("game_date")
        season_group = group
        if "season" in group and group["season"].notna().any():
            latest_season = group.loc[group["season"].notna(), "season"].iloc[-1]
            season_group = group[group["season"].eq(latest_season)]
        recent = group.tail(5)
        last_date = group["game_date"].max()
        pts_recent = float(recent["pts"].mean())
        reb_recent = float(recent["reb"].mean())
        ast_recent = float(recent["ast"].mean())
        pts_season = float(season_group["pts"].mean())
        impact = pts_recent + 0.7 * reb_recent + ast_recent
        tag_parts = []
        if pts_recent >= float(group["pts"].mean()) + 3:
            tag_parts.append("Em alta")
        if pts_recent >= 20:
            tag_parts.append("Cestinha")
        if reb_recent >= 9:
            tag_parts.append("Reboteiro")
        if ast_recent >= 7:
            tag_parts.append("Criador")
        result.append({
            "player_id": int(player_id) if str(player_id).isdigit() else player_id,
            "player_name": str(group["player_name"].dropna().iloc[-1]),
            "team": str(group["team"].dropna().iloc[-1]),
            "minutes_recent": float(recent["minutes"].mean()),
            "pts_recent": pts_recent, "reb_recent": reb_recent, "ast_recent": ast_recent,
            "pts_season": pts_season, "pts_delta": pts_recent - pts_season,
            "last_game_date": last_date, "impact_recent": impact,
            "tag": " · ".join(tag_parts) if tag_parts else "Consistente",
        })
    return pd.DataFrame(result)


def team_highlights(form_table: pd.DataFrame, team: str, top_n: int = 3) -> pd.DataFrame:
    if form_table is None or form_table.empty or "team" not in form_table:
        return pd.DataFrame(columns=list(form_table.columns) if isinstance(form_table, pd.DataFrame) else [])
    aliases = {x.casefold() for x in team_aliases(team)}
    selected = form_table[form_table["team"].astype(str).str.casefold().isin(aliases)].copy()
    if selected.empty:
        return selected
    if "last_game_date" in selected and "last_game_date" in form_table:
        latest_available = pd.to_datetime(form_table["last_game_date"], errors="coerce").max()
        last_dates = pd.to_datetime(selected["last_game_date"], errors="coerce")
        age_days = (latest_available.normalize() - last_dates.dt.normalize()).dt.days
        selected = selected[age_days.le(45)].copy()
    if "minutes_recent" in selected:
        selected = selected[pd.to_numeric(selected["minutes_recent"], errors="coerce").ge(10)].copy()
    if selected.empty:
        return selected
    if "impact_recent" not in selected:
        selected["impact_recent"] = selected["pts_recent"] + 0.7 * selected["reb_recent"] + selected["ast_recent"]
    if "tag" not in selected:
        selected["tag"] = "Consistente"
    return selected.sort_values("impact_recent", ascending=False).head(max(1, int(top_n))).reset_index(drop=True)


def game_headliner(home_players: pd.DataFrame, away_players: pd.DataFrame) -> dict | None:
    frames = [frame for frame in (home_players, away_players) if frame is not None and not frame.empty]
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    if "impact_recent" not in combined:
        combined["impact_recent"] = combined["pts_recent"] + 0.7 * combined["reb_recent"] + combined["ast_recent"]
    return combined.sort_values("impact_recent", ascending=False).iloc[0].to_dict()


def games_for_date(schedule: pd.DataFrame, selected_day: date) -> pd.DataFrame:
    if schedule is None or schedule.empty or "game_date" not in schedule:
        return pd.DataFrame(columns=list(schedule.columns) if isinstance(schedule, pd.DataFrame) else [])
    data = schedule.copy()
    data["_date"] = pd.to_datetime(data["game_date"], errors="coerce").dt.date
    data = data[data["_date"].eq(selected_day)].copy()
    if "game_datetime_utc" in data:
        data["_sort_time"] = pd.to_datetime(data["game_datetime_utc"], errors="coerce", utc=True)
        data = data.sort_values(["_sort_time", "game_id"], na_position="last")
        data = data.drop(columns=["_sort_time"])
    return data.drop(columns=["_date"]).reset_index(drop=True)


def format_tipoff(value) -> str:
    if value is None or pd.isna(value):
        return "Horário a confirmar"
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    br = stamp.tz_convert(BRASILIA)
    et = stamp.tz_convert(EASTERN)
    next_day = " · dia seguinte em Brasília" if br.date() != et.date() else ""
    return f"{br:%H:%M} (Brasília) · {et:%H:%M} ET{next_day}"


def status_label(value) -> str:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return "—"
    return {1: "Agendado", 2: "Em andamento", 3: "Encerrado"}.get(status, "—")
