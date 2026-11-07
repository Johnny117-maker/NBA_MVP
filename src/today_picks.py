"""Seleção de atletas da rodada e palpites esportivos baseados no histórico local."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from .daily_games import games_for_date, team_highlights, team_rest_days
from .data import team_game_history, team_snapshot
from .model import GamePrediction, ModelBundle, predict_game


def daily_team_picks(db_path, games, selected_day: date) -> dict:
    from .data import load_real_games
    from .model import train_models

    history = load_real_games(db_path)
    history = history.loc[pd.to_datetime(history.game_date).dt.date < selected_day]
    bundle = train_models(history)
    result = {}
    for game in games:
        row = pd.Series({"home_team_name": game.home, "away_team_name": game.away})
        from .nba_teams import TEAM_ABBREVIATION_TO_NAME

        row["home_team_name"] = TEAM_ABBREVIATION_TO_NAME.get(game.home, game.home)
        row["away_team_name"] = TEAM_ABBREVIATION_TO_NAME.get(game.away, game.away)
        try:
            pick = build_matchup_pick(bundle, history, row, selected_day)
            result[game.key] = {
                **asdict(pick),
                "last_game_date": pick.last_game_date.isoformat(),
                "confidence": pick.confidence,
            }
        except (ValueError, KeyError):
            continue
    return result


def upcoming_games(schedule: pd.DataFrame, selected_day: date, now: pd.Timestamp) -> pd.DataFrame:
    """Só partidas agendadas, do dia pedido, cujo início conhecido ainda não passou.

    Arquivos periódicos podem manter status agendado após o início: o horário UTC
    é uma segunda barreira. Horários desconhecidos permanecem com aviso na UI.
    """
    games = games_for_date(schedule, selected_day)
    if games.empty:
        return games
    status = pd.to_numeric(games["game_status"], errors="coerce")
    tipoff = pd.to_datetime(games["game_datetime_utc"], errors="coerce", utc=True)
    now = pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    return games[status.eq(1) & (tipoff.isna() | tipoff.gt(now))].reset_index(drop=True)


def round_highlights(form: pd.DataFrame, games: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    """Une os destaques apenas das equipes da rodada, preservando o confronto."""
    frames = []
    for _, game in games.iterrows():
        if pd.to_numeric(game.get("game_status"), errors="coerce") == 4:
            continue
        for side, opponent, is_home in (("away", "home", False), ("home", "away", True)):
            candidates = team_highlights(form, str(game[f"{side}_team_tricode"]), top_n=top_n).copy()
            if candidates.empty:
                continue
            candidates["game_id"] = str(game["game_id"])
            candidates["team_code"] = str(game[f"{side}_team_tricode"])
            candidates["opponent_name"] = str(game[f"{opponent}_team_name"])
            candidates["is_home"] = is_home
            candidates["matchup"] = f"{game['away_team_tricode']} @ {game['home_team_tricode']}"
            candidates["game_datetime_utc"] = game.get("game_datetime_utc")
            frames.append(candidates)
    if not frames:
        return pd.DataFrame()
    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(["game_id", "player_id"])
        .sort_values(["impact_recent", "player_name"], ascending=[False, True])
        .reset_index(drop=True)
    )


@dataclass(frozen=True)
class MatchupPick:
    favorite: str
    probability: float
    prediction: GamePrediction
    last_game_date: pd.Timestamp
    history_age_days: int

    @property
    def confidence(self) -> str:
        return "Baixa · histórico antigo" if self.history_age_days > 14 else self.prediction.confidence


def build_matchup_pick(
    bundle: ModelBundle,
    history: pd.DataFrame,
    game: pd.Series,
    selected_day: date,
) -> MatchupPick:
    # Defesa adicional: mesmo um chamador com histórico não recortado não usa placares do dia.
    before = history[pd.to_datetime(history["game_date"]).dt.date < selected_day]
    home, away = str(game["home_team_name"]), str(game["away_team_name"])
    prediction = predict_game(
        bundle,
        team_snapshot(before, home, as_of=selected_day),
        team_snapshot(before, away, as_of=selected_day),
        team_rest_days(before, home, selected_day),
        team_rest_days(before, away, selected_day),
    )
    latest = min(team_game_history(before, team)["game_date"].max() for team in (home, away))
    return MatchupPick(
        favorite=home if prediction.home_win_probability >= 0.5 else away,
        probability=max(prediction.home_win_probability, prediction.away_win_probability),
        prediction=prediction,
        last_game_date=pd.Timestamp(latest),
        history_age_days=max(0, (selected_day - pd.Timestamp(latest).date()).days),
    )
