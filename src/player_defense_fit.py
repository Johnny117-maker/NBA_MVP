"""Associações históricas entre produção do jogador e concessão defensiva pré-jogo."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .history_normalize import game_phase
from .history_store import connect_history, history_root, read_assets
from .live_types import minutes

DIMENSIONS = {
    "paint_profile": "Garrafão",
    "perimeter_profile": "Perímetro",
    "overall_profile": "Eficiência geral",
}


def defense_context(boxes: pd.DataFrame) -> pd.DataFrame:
    """Classificação contemporânea da liga usando somente jogos de datas anteriores."""
    if boxes.empty:
        return pd.DataFrame()
    own = boxes.merge(
        boxes,
        left_on=["season", "phase", "game_id", "opponent"],
        right_on=["season", "phase", "game_id", "team"],
        suffixes=("", "_opp"),
        validate="one_to_one",
    )
    own["game_date"] = pd.to_datetime(own["game_date"])
    own["poss"] = 0.5 * (
        (own.fga + 0.44 * own.fta - own.oreb + own.tov)
        + (own.fga_opp + 0.44 * own.fta_opp - own.oreb_opp + own.tov_opp)
    )
    values = ["points_opp", "paint_opp", "fg3a_opp", "fg3m_opp", "poss"]
    all_frames = []
    for (season, phase), season_rows in own.groupby(["season", "phase"]):
        calendar = pd.DatetimeIndex(sorted(season_rows.game_date.unique()))
        frames = []
        for team, team_rows in season_rows.groupby("team"):
            team_rows = team_rows.sort_values("game_date").set_index("game_date")
            if team_rows.index.has_duplicates:
                raise ValueError(
                    "Equipe com duas partidas na mesma data: contexto exige horário para desempatar."
                )
            rolling = team_rows[values].rolling(10, min_periods=5).sum()
            # Reindexar no calendário de TODA a liga antes de deslocar impede usar
            # a partida do próprio dia, inclusive na comparação com as outras equipes.
            prior = rolling.reindex(calendar).ffill().shift(1)
            prior["prior_paint"] = 100 * prior.paint_opp / prior.poss.replace(0, np.nan)
            prior["prior_3pa"] = 100 * prior.fg3a_opp / prior.poss.replace(0, np.nan)
            prior["prior_3p_pct"] = prior.fg3m_opp / prior.fg3a_opp.replace(0, np.nan)
            prior["prior_drtg"] = 100 * prior.points_opp / prior.poss.replace(0, np.nan)
            prior["team"], prior["season"], prior["phase"] = team, season, phase
            prior.index.name = "game_date"
            frames.append(prior.reset_index())
        league = pd.concat(frames, ignore_index=True)
        league["perimeter_score"] = (
            league.groupby("game_date")["prior_3pa"].rank(pct=True)
            + league.groupby("game_date")["prior_3p_pct"].rank(pct=True)
        ) / 2
        for target, metric in (
            ("paint_profile", "prior_paint"),
            ("perimeter_profile", "perimeter_score"),
            ("overall_profile", "prior_drtg"),
        ):
            group = league.groupby("game_date")[metric]
            low, high = (
                group.transform(lambda s: s.quantile(1 / 3)),
                group.transform(lambda s: s.quantile(2 / 3)),
            )
            league[target] = np.select(
                [league[metric].isna(), league[metric].lt(low), league[metric].gt(high)],
                ["Sem amostra prévia", "Menor concessão", "Maior concessão"],
                default="Intermediária",
            )
        all_frames.append(league[["season", "phase", "game_date", "team", *DIMENSIONS]])
    return pd.concat(all_frames, ignore_index=True)


def player_game_log(db_path: str | Path, player_id: int, season: str, phase: str) -> pd.DataFrame:
    assets = read_assets(db_path)
    year = int(season[:4]) + 1
    match = (
        assets.loc[assets.tag.eq("nba_stats_player_boxscores") & assets.year.eq(year)]
        if not assets.empty
        else pd.DataFrame()
    )
    if not match.empty:
        root = history_root(db_path)
        rows = pd.read_parquet(root / match.iloc[0].relative_path, filters=[("person_id", "==", player_id)])
        rows = rows.loc[rows.game_id.map(game_phase).eq(phase)].copy()
        schedule_asset = assets.loc[assets.tag.eq("nba_stats_schedules") & assets.year.eq(year)].iloc[0]
        schedule = pd.read_parquet(root / schedule_asset.relative_path)
        rows = rows.merge(
            schedule[
                ["game_id", "game_date", "home_team_abbreviation", "away_team_abbreviation"]
            ].drop_duplicates("game_id"),
            on="game_id",
        )
        rows["opponent"] = rows.away_team_abbreviation.where(
            rows.team_tricode.eq(rows.home_team_abbreviation), rows.home_team_abbreviation
        )
        rows["minutes"] = rows.minutes.map(minutes)
        rows = rows.rename(
            columns={"points": "pts", "field_goals_made": "fgm", "field_goals_attempted": "fga"}
        )
        return rows[["game_id", "game_date", "opponent", "minutes", "pts", "fgm", "fga"]]
    if phase != "Temporada regular":
        return pd.DataFrame()
    with sqlite3.connect(db_path) as connection:
        return pd.read_sql_query(
            "SELECT game_id,game_date,opponent,minutes,pts,fgm,fga FROM player_game_stats "
            "WHERE player_id=? AND season=?",
            connection,
            params=(player_id, season),
        )


def fit_summary(
    logs: pd.DataFrame, context: pd.DataFrame, season: str, phase: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if logs.empty or context.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = logs.loc[logs.minutes.ge(10)].copy()
    rows["game_date"] = pd.to_datetime(rows.game_date).dt.normalize()
    observed = context.loc[context.season.eq(season) & context.phase.eq(phase)]
    joined = rows.merge(
        observed,
        left_on=["game_date", "opponent"],
        right_on=["game_date", "team"],
        how="left",
        validate="many_to_one",
    )
    result = []
    for column, label in DIMENSIONS.items():
        comparable = joined.loc[joined[column].notna() & joined[column].ne("Sem amostra prévia")]
        for bucket, group in comparable.groupby(column):
            other = comparable.loc[comparable[column].ne(bucket)]
            rate = 36 * group.pts.sum() / group.minutes.sum()
            reference = 36 * other.pts.sum() / other.minutes.sum() if len(other) else np.nan
            eligible = (
                len(group) >= 10
                and len(other) >= 10
                and group.minutes.sum() >= 200
                and other.minutes.sum() >= 200
            )
            low = high = np.nan
            if eligible:
                rng = np.random.default_rng(42)
                a = rng.integers(0, len(group), size=(1000, len(group)))
                b = rng.integers(0, len(other), size=(1000, len(other)))
                differences = 36 * group.pts.to_numpy()[a].sum(axis=1) / group.minutes.to_numpy()[a].sum(
                    axis=1
                ) - 36 * other.pts.to_numpy()[b].sum(axis=1) / other.minutes.to_numpy()[b].sum(axis=1)
                low, high = np.quantile(differences, [0.025, 0.975])
            interpretation = (
                "Amostra insuficiente"
                if not eligible
                else "Produção maior observada"
                if low > 0
                else "Produção menor observada"
                if high < 0
                else "Diferença incerta"
            )
            result.append(
                {
                    "dimension": label,
                    "profile": bucket,
                    "games": len(group),
                    "comparison_games": len(other),
                    "pts_game": group.pts.mean(),
                    "minutes_game": group.minutes.mean(),
                    "pts36": rate,
                    "comparison_pts36": reference,
                    "difference_pts36": rate - reference,
                    "difference_low": low,
                    "difference_high": high,
                    "interpretation": interpretation,
                }
            )
    return pd.DataFrame(result), joined


def analyze_player_fit(db_path: str | Path, player_id: int, season: str, phase: str):
    with connect_history(db_path) as connection:
        boxes = pd.read_sql_query(
            "SELECT * FROM team_boxes WHERE season=? AND phase=?", connection, params=(season, phase)
        )
    return fit_summary(
        player_game_log(db_path, player_id, season, phase), defense_context(boxes), season, phase
    )
