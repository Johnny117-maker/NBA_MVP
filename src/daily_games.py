from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .nba_schedule import SCHEDULE_COLUMNS
from .nba_teams import TEAM_ABBREVIATION_TO_NAME

NBA_TIMEZONE = ZoneInfo("America/New_York")
BRASILIA_TIMEZONE = ZoneInfo("America/Sao_Paulo")

STATUS_LABELS = {1: "Agendado", 2: "Ao vivo", 3: "Encerrado"}

RECENT_WINDOW = 5
# Diferença (pontos por jogo) entre a forma recente e a média da temporada a
# partir da qual um jogador é marcado como "em alta"/"em baixa".
FORM_THRESHOLD = 3.0
# Peso de cada estatística no índice de destaque (forma recente).
IMPACT_WEIGHTS = {"pts_recent": 1.0, "reb_recent": 0.7, "ast_recent": 1.0}
LEADER_LABELS = {
    "pts_recent": "Cestinha",
    "reb_recent": "Reboteiro",
    "ast_recent": "Armador",
}

FORM_TABLE_COLUMNS = [
    "player_id",
    "player_name",
    "team",
    "last_game_date",
    "games",
    "minutes_recent",
    "pts_recent",
    "reb_recent",
    "ast_recent",
    "games_season",
    "pts_season",
    "reb_season",
    "ast_season",
    "impact_recent",
    "pts_delta",
]


def today_et() -> date:
    """Data de hoje no fuso da NBA (costa leste dos EUA) — o "dia" do calendário."""
    return datetime.now(NBA_TIMEZONE).date()


def games_for_date(schedule: pd.DataFrame | None, day: date) -> pd.DataFrame:
    """Jogos do calendário em um dia (data da NBA), em ordem de horário."""
    if schedule is None or schedule.empty:
        return pd.DataFrame(columns=SCHEDULE_COLUMNS)
    days = pd.to_datetime(schedule["game_date"], errors="coerce").dt.date
    games = schedule[days == day].copy()
    if "game_datetime_utc" in games.columns:
        games = games.sort_values("game_datetime_utc", na_position="last")
    return games.reset_index(drop=True)


def format_tipoff(value: object) -> str:
    """Horário de início em Brasília e em ET, a partir de um timestamp UTC."""
    if value is None or pd.isna(value):
        return "Horário a confirmar"
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    brasilia = stamp.tz_convert(BRASILIA_TIMEZONE)
    eastern = stamp.tz_convert(NBA_TIMEZONE)
    suffix = " (dia seguinte)" if brasilia.date() != eastern.date() else ""
    return f"{brasilia:%H:%M} (Brasília){suffix} · {eastern:%H:%M} ET"


def status_label(status: object) -> str:
    try:
        return STATUS_LABELS.get(int(status), "—")  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return "—"


def team_aliases(team_code: str) -> set[str]:
    """Sigla e nome completo: `player_game_stats.team` usa a sigla, a base
    demonstrativa usa o nome completo."""
    code = str(team_code).strip().upper()
    aliases = {code}
    name = TEAM_ABBREVIATION_TO_NAME.get(code)
    if name:
        aliases.add(name)
    return aliases


def build_form_table(player_games: pd.DataFrame, recent_window: int = RECENT_WINDOW) -> pd.DataFrame:
    """Uma linha por jogador: forma recente (últimos jogos) e média da temporada
    mais recente dele. Calculada uma vez e reaproveitada por todos os times.

    Só conta jogos com minutos > 0. "Time atual" = time do último jogo.
    """
    if player_games.empty:
        return pd.DataFrame(columns=FORM_TABLE_COLUMNS)

    played = player_games[player_games["minutes"] > 0].copy()
    if played.empty:
        return pd.DataFrame(columns=FORM_TABLE_COLUMNS)
    if "season" not in played.columns:
        played["season"] = "all"
    played = played.sort_values(["player_id", "game_date"])

    grouped = played.groupby("player_id")
    last = grouped.tail(1).set_index("player_id")
    games = grouped.size().rename("games")

    recent = (
        grouped.tail(recent_window)
        .groupby("player_id")
        .agg(
            minutes_recent=("minutes", "mean"),
            pts_recent=("pts", "mean"),
            reb_recent=("reb", "mean"),
            ast_recent=("ast", "mean"),
        )
    )

    last_season = played["player_id"].map(last["season"])
    in_season = played[played["season"] == last_season]
    season = in_season.groupby("player_id").agg(
        games_season=("pts", "size"),
        pts_season=("pts", "mean"),
        reb_season=("reb", "mean"),
        ast_season=("ast", "mean"),
    )

    table = pd.concat(
        [
            last[["player_name", "team", "game_date"]].rename(columns={"game_date": "last_game_date"}),
            games,
            recent,
            season,
        ],
        axis=1,
    ).reset_index()
    table["impact_recent"] = sum(table[column] * weight for column, weight in IMPACT_WEIGHTS.items())
    table["pts_delta"] = table["pts_recent"] - table["pts_season"]
    return table[FORM_TABLE_COLUMNS]


def team_highlights(
    form_table: pd.DataFrame,
    team_code: str,
    top_n: int = 3,
    min_games: int = 10,
    min_minutes: float = 15.0,
    max_inactive_days: int = 21,
) -> pd.DataFrame:
    """Jogadores em destaque de um time, por índice de impacto na forma recente.

    Só entram jogadores com histórico mínimo, minutos relevantes e que jogaram
    nos últimos `max_inactive_days` dias da base (descarta quem saiu do time ou
    está parado há muito tempo — a base não tem dados de lesão). A coluna `tag`
    marca os líderes do time em pontos/rebotes/assistências e a tendência.
    """
    if form_table.empty:
        return form_table.assign(tag=pd.Series(dtype=object))

    cutoff = form_table["last_game_date"].max() - pd.Timedelta(days=max_inactive_days)
    eligible = form_table[
        form_table["team"].isin(team_aliases(team_code))
        & (form_table["games"] >= min_games)
        & (form_table["minutes_recent"] >= min_minutes)
        & (form_table["last_game_date"] >= cutoff)
    ].copy()
    if eligible.empty:
        return eligible.assign(tag="")

    tags: dict[object, list[str]] = {index: [] for index in eligible.index}
    for column, label in LEADER_LABELS.items():
        tags[eligible[column].idxmax()].append(label)
    for index, delta in eligible["pts_delta"].items():
        if pd.isna(delta):
            continue
        if delta >= FORM_THRESHOLD:
            tags[index].append("🔥 Em alta")
        elif delta <= -FORM_THRESHOLD:
            tags[index].append("🥶 Em baixa")
    eligible["tag"] = [" · ".join(tags[index]) for index in eligible.index]

    return eligible.sort_values("impact_recent", ascending=False).head(top_n).reset_index(drop=True)


def game_headliner(home: pd.DataFrame, away: pd.DataFrame) -> pd.Series | None:
    """Destaque da partida: maior impacto recente entre os dois times."""
    both = pd.concat([home, away], ignore_index=True)
    if both.empty:
        return None
    return both.sort_values("impact_recent", ascending=False).iloc[0]
