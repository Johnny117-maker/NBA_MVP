"""Tabela por zona e jogo, janelas pré-jogo e defesa do adversário por zona."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..player_features import DEFAULT_REST_DAYS, EMA_HALFLIFE_SLOW
from ..shot_features import ZONES, add_shot_value
from .config import ZONE_FG_PCT_PRIOR, ZONE_SHARE_PRIOR


def _regression_pipeline() -> Pipeline:
    return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=2.0))])


def _share_features(zone: str) -> list[str]:
    return [f"share_avg10_{zone}", f"defense_share_allowed_avg_{zone}", "games_since_trade", "rest_days"]


def _efficiency_features(zone: str) -> list[str]:
    return [f"fgpct_avg10_{zone}", f"defense_fgpct_allowed_avg_{zone}", "games_since_trade", "rest_days"]


def build_zone_game_table(shots: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (jogador, jogo): tentativas/conversões por zona, em formato largo.

    Base para o resto do módulo — o pivô de `player_shots` (uma linha por
    arremesso) para o nível em que os modelos treinam (uma linha por jogo).
    """
    data = add_shot_value(shots)
    made = data["shot_made"].astype(bool)
    data["points"] = np.where(made, data["shot_value"], 0)

    keys = ["player_id", "player_name", "game_id", "game_date", "season", "team_name", "opponent"]
    totals = data.groupby(keys, as_index=False).agg(
        total_fga=("shot_attempted", "size"),
        total_fg_makes=("shot_made", "sum"),
        total_fg_points=("points", "sum"),
    )

    zone_attempts = (
        data.pivot_table(
            index=["player_id", "game_id"],
            columns="shot_zone_basic",
            values="shot_attempted",
            aggfunc="size",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("attempts_")
    )
    zone_makes = (
        data.pivot_table(
            index=["player_id", "game_id"],
            columns="shot_zone_basic",
            values="shot_made",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("makes_")
    )

    wide = totals.merge(zone_attempts, on=["player_id", "game_id"]).merge(
        zone_makes, on=["player_id", "game_id"]
    )
    for zone in ZONES:
        wide[f"share_{zone}"] = wide[f"attempts_{zone}"] / wide["total_fga"].replace(0, np.nan)
        wide[f"share_{zone}"] = wide[f"share_{zone}"].fillna(0.0)
        wide[f"fg_pct_{zone}"] = wide[f"makes_{zone}"] / wide[f"attempts_{zone}"].replace(0, np.nan)

    wide["game_date"] = pd.to_datetime(wide["game_date"])
    return wide.sort_values(["player_id", "game_date"]).reset_index(drop=True)


def _assign_zone_team_stints(zone_games: pd.DataFrame) -> pd.DataFrame:
    """Mesmo princípio de `player_features.py::assign_team_stints`, mas sobre
    `team_name` (nome completo, como vem de `player_shots`) em vez de `team`
    (sigla, como vem de `player_game_stats`) — os dois módulos guardam o time
    em formatos diferentes (ver README)."""
    games = zone_games.sort_values(["player_id", "game_date"]).copy()
    team_changed = games.groupby("player_id")["team_name"].transform(
        lambda team: team != team.shift(1)
    )
    stint_id = team_changed.groupby(games["player_id"]).cumsum()
    games["games_since_trade"] = games.groupby([games["player_id"], stint_id]).cumcount()
    return games


def _per_player_zone_rolling(group: pd.DataFrame) -> pd.DataFrame:
    """Médias móveis exponenciais por zona, sem vazamento (`shift(1)` antes do `ewm`).

    `share_avg10_<zona>` usa todos os jogos (participação é 0 num jogo sem
    tentativa ali). `fgpct_avg10_<zona>` usa `ignore_na=True`: jogos sem
    tentativa naquela zona viram `NaN` em `fg_pct_<zona>` e são pulados no
    peso da média, em vez de contar como "0% de aproveitamento" ou quebrar o
    espaçamento temporal da EWM.
    """
    group = group.sort_values("game_date").copy()
    group["rest_days"] = (group["game_date"] - group["game_date"].shift(1)).dt.days
    for zone in ZONES:
        group[f"share_avg10_{zone}"] = (
            group[f"share_{zone}"].shift(1).ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
        )
        group[f"fgpct_avg10_{zone}"] = (
            group[f"fg_pct_{zone}"]
            .shift(1)
            .ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1, ignore_na=True)
            .mean()
        )
    return group


def add_zone_rolling_features(zone_games: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `share_avg10_<zona>`/`fgpct_avg10_<zona>`/`games_since_trade`/`rest_days`.

    Tendência própria do jogador até aquele jogo (sem vazamento) — metade da
    entrada dos modelos de zona; a outra metade é a defesa do adversário
    (`add_opponent_zone_defense_features`).
    """
    games = _assign_zone_team_stints(zone_games)
    player_ids = games[["player_id"]]
    games = games.groupby("player_id", group_keys=False).apply(
        _per_player_zone_rolling, include_groups=False
    )
    games = games.join(player_ids)
    games["rest_days"] = games["rest_days"].fillna(DEFAULT_REST_DAYS).astype(int)

    for zone in ZONES:
        games[f"share_avg10_{zone}"] = games[f"share_avg10_{zone}"].fillna(ZONE_SHARE_PRIOR[zone])
        games[f"fgpct_avg10_{zone}"] = games[f"fgpct_avg10_{zone}"].fillna(ZONE_FG_PCT_PRIOR[zone])

    return games.sort_values("game_date").reset_index(drop=True)


def _team_zone_defense_games(shots: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (adversário, jogo): quanto ele permitiu em cada zona
    naquele jogo, somando todos os arremessos coletados contra ele (podem ser
    de vários jogadores diferentes) — insumo da defesa por zona (seção 9)."""
    data = add_shot_value(shots)

    totals = data.groupby(["opponent", "game_id", "game_date"], as_index=False).agg(
        total_fga=("shot_attempted", "size"),
    )
    zone_attempts = (
        data.pivot_table(
            index=["opponent", "game_id"],
            columns="shot_zone_basic",
            values="shot_attempted",
            aggfunc="size",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("attempts_")
    )
    zone_makes = (
        data.pivot_table(
            index=["opponent", "game_id"],
            columns="shot_zone_basic",
            values="shot_made",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=ZONES, fill_value=0)
        .add_prefix("makes_")
    )

    merged = totals.merge(zone_attempts, on=["opponent", "game_id"]).merge(
        zone_makes, on=["opponent", "game_id"]
    )
    for zone in ZONES:
        merged[f"share_allowed_{zone}"] = merged[f"attempts_{zone}"] / merged["total_fga"].replace(
            0, np.nan
        )
        merged[f"share_allowed_{zone}"] = merged[f"share_allowed_{zone}"].fillna(0.0)
        merged[f"fg_pct_allowed_{zone}"] = merged[f"makes_{zone}"] / merged[f"attempts_{zone}"].replace(
            0, np.nan
        )

    merged["game_date"] = pd.to_datetime(merged["game_date"])
    return merged.sort_values(["opponent", "game_date"]).reset_index(drop=True)


def _expanding_zone_defense(group: pd.DataFrame) -> pd.DataFrame:
    """Média expansiva (não EWMA) de quanto o time permitiu por zona, só com
    jogos anteriores — mesmo raciocínio de
    `player_features.py::_expanding_defense` (`opponent_def_rating`): a
    tendência defensiva de um time por zona muda pouco de uma semana para
    outra, então uma janela curta seria mais ruído do que sinal."""
    group = group.sort_values("game_date").copy()
    for zone in ZONES:
        group[f"defense_share_allowed_avg_{zone}"] = (
            group[f"share_allowed_{zone}"].shift(1).expanding(min_periods=1).mean()
        )
        group[f"defense_fgpct_allowed_avg_{zone}"] = (
            group[f"fg_pct_allowed_{zone}"]
            .shift(1)
            .expanding(min_periods=1)
            .mean()
        )
    return group


def add_opponent_zone_defense_features(zone_games: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `defense_share_allowed_avg_<zona>`/`defense_fgpct_allowed_avg_<zona>`:
    quanto o adversário daquele jogo costumava permitir por zona até essa data
    (sem vazamento). `player_shots.opponent`/`.team_name` já usam o mesmo
    formato de nome completo dos dois lados (ao contrário de
    `player_game_stats`, que mistura sigla e nome — ver README), então o
    `merge_asof` não precisa de nenhuma tradução extra.
    """
    defense_games = _team_zone_defense_games(shots)
    opponent_column = defense_games[["opponent"]]
    defense_games = defense_games.groupby("opponent", group_keys=False).apply(
        _expanding_zone_defense, include_groups=False
    )
    defense_games = defense_games.join(opponent_column)

    defense_feature_columns = [
        f"defense_{kind}_avg_{zone}" for zone in ZONES for kind in ("share_allowed", "fgpct_allowed")
    ]
    defense_lookup = (
        defense_games[["opponent", "game_date", *defense_feature_columns]]
        .sort_values("game_date")
        .reset_index(drop=True)
    )

    merged = pd.merge_asof(
        zone_games.sort_values("game_date").reset_index(drop=True),
        defense_lookup,
        on="game_date",
        by="opponent",
        direction="backward",
    )
    for zone in ZONES:
        merged[f"defense_share_allowed_avg_{zone}"] = merged[
            f"defense_share_allowed_avg_{zone}"
        ].fillna(ZONE_SHARE_PRIOR[zone])
        merged[f"defense_fgpct_allowed_avg_{zone}"] = merged[
            f"defense_fgpct_allowed_avg_{zone}"
        ].fillna(ZONE_FG_PCT_PRIOR[zone])
    return merged.sort_values("game_date").reset_index(drop=True)


def add_zone_model_features(shots: pd.DataFrame) -> pd.DataFrame:
    """Atalho: `build_zone_game_table` + as duas rodadas de features (própria
    tendência e defesa do adversário), na ordem certa."""
    zone_games = build_zone_game_table(shots)
    zone_games = add_zone_rolling_features(zone_games)
    return add_opponent_zone_defense_features(zone_games, shots)
