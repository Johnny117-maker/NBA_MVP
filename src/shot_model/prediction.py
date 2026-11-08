"""Distribuição prevista por zona, pontos esperados e fotos ao vivo."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..player_features import DEFAULT_REST_DAYS, EMA_HALFLIFE_SLOW
from ..shot_features import THREE_POINT_ZONES, ZONE_LABELS_PT, ZONES, opponent_zone_defense
from .config import ZoneModelBundle
from .features import _efficiency_features, _share_features


def predict_zone_distribution(bundle: ZoneModelBundle, rows: pd.DataFrame) -> pd.DataFrame:
    """Previsão por zona (participação normalizada de FGA + FG% esperado), em lote.

    `rows` precisa trazer as features de `add_zone_model_features` (treino/
    avaliação) ou de `live_zone_snapshot` (previsão de um jogo futuro).
    Devolve formato longo — uma linha por (`row_index`, zona) — para caber
    tanto uma única previsão ao vivo quanto um lote inteiro de walk-forward
    numa só chamada.
    """
    raw_shares: dict[str, np.ndarray] = {}
    predicted_fg_pcts: dict[str, np.ndarray] = {}
    for zone in ZONES:
        share_features = _share_features(zone)
        raw_shares[zone] = np.maximum(0.0, bundle.share_models[zone].predict(rows[share_features]))

        fg_pct_model = bundle.fg_pct_models[zone]
        if fg_pct_model is not None:
            predicted_fg_pcts[zone] = np.clip(
                fg_pct_model.predict(rows[_efficiency_features(zone)]), 0.0, 1.0
            )
        else:
            predicted_fg_pcts[zone] = np.full(len(rows), bundle.league_avg_fg_pct[zone])

    share_matrix = np.column_stack([raw_shares[zone] for zone in ZONES])
    totals = share_matrix.sum(axis=1)
    totals_safe = np.where(totals > 0, totals, 1.0)
    normalized = np.where(
        totals[:, None] > 0, share_matrix / totals_safe[:, None], 1.0 / len(ZONES)
    )

    frames = []
    for i, zone in enumerate(ZONES):
        frames.append(
            pd.DataFrame(
                {
                    "row_index": rows.index,
                    "shot_zone_basic": zone,
                    "zone_label": ZONE_LABELS_PT.get(zone, zone),
                    "predicted_share": normalized[:, i],
                    "predicted_fg_pct": predicted_fg_pcts[zone],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def expected_fg_points(zone_predictions: pd.DataFrame, predicted_fga: pd.Series) -> pd.Series:
    """Combina distribuição por zona + FGA previstos em pontos esperados de
    bola-de-quadra, por linha original — o "Pontos totais" (só campo) do
    diagrama da seção 10. `predicted_fga` precisa ter o mesmo índice usado em
    `predict_zone_distribution` (a coluna `row_index` do resultado). Lance
    livre fica fora daqui: combine com `player_model/prediction.py::predict_player_game`
    (FTA × aproveitamento de lance livre do jogador) para o total do jogo.
    """
    data = zone_predictions.copy()
    data["predicted_fga_zone"] = data["predicted_share"] * data["row_index"].map(predicted_fga)
    data["shot_value"] = np.where(data["shot_zone_basic"].isin(THREE_POINT_ZONES), 3, 2)
    data["predicted_points_zone"] = (
        data["predicted_fga_zone"] * data["predicted_fg_pct"] * data["shot_value"]
    )
    return data.groupby("row_index")["predicted_points_zone"].sum().rename("predicted_fg_points")


def opponent_zone_defense_snapshot(shots: pd.DataFrame, defending_team: str) -> dict[str, float]:
    """Estado atual (todos os arremessos já coletados, sem corte de data) da
    defesa por zona de um adversário — para prever um jogo genuinamente
    futuro. Diferente de `add_opponent_zone_defense_features` (que usa média
    expansiva sem vazamento, para treino/avaliação): aqui não há "vazamento"
    a evitar, é literalmente o estado mais atual que a base tem.
    """
    defense = opponent_zone_defense(shots)
    team_rows = defense[defense["defending_team"] == defending_team].set_index("shot_zone_basic")
    total_attempts = float(team_rows["attempts_against"].sum()) if not team_rows.empty else 0.0

    snapshot: dict[str, float] = {}
    for zone in ZONES:
        if zone in team_rows.index and total_attempts > 0:
            snapshot[f"defense_share_allowed_avg_{zone}"] = float(
                team_rows.loc[zone, "attempts_against"] / total_attempts
            )
            snapshot[f"defense_fgpct_allowed_avg_{zone}"] = float(team_rows.loc[zone, "fg_pct_against"])
        else:
            snapshot[f"defense_share_allowed_avg_{zone}"] = float("nan")
            snapshot[f"defense_fgpct_allowed_avg_{zone}"] = float("nan")
    return snapshot


def live_zone_snapshot(
    zone_games_with_features: pd.DataFrame,
    player_id: int,
    defending_team: str | None,
    shots: pd.DataFrame,
    rest_days: int = DEFAULT_REST_DAYS,
) -> pd.DataFrame:
    """Estado atual (sem `shift`) de um jogador para prever um jogo futuro —
    mesmo princípio de `player_metrics.py::player_snapshot`: recalcula a EWMA
    incluindo o último jogo já disputado, em vez de usar a versão "defasada
    em um jogo" que o treino usa (lá o `shift(1)` existe para não vazar o
    resultado do próprio jogo que está sendo previsto; aqui não existe esse
    risco, o jogo que queremos prever ainda não aconteceu).
    """
    player_rows = zone_games_with_features[
        zone_games_with_features["player_id"] == player_id
    ].sort_values("game_date")
    if player_rows.empty:
        raise ValueError(f"Nenhum arremesso coletado para o jogador {player_id}.")

    latest = player_rows.iloc[-1]
    features: dict[str, float] = {
        "games_since_trade": float(latest["games_since_trade"]),
        "rest_days": float(rest_days),
    }

    defense_snapshot = (
        opponent_zone_defense_snapshot(shots, defending_team) if defending_team else {}
    )

    for zone in ZONES:
        share_series = player_rows[f"share_{zone}"].ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
        features[f"share_avg10_{zone}"] = float(share_series.iloc[-1])

        eff_rows = player_rows[player_rows[f"attempts_{zone}"] > 0]
        if not eff_rows.empty:
            fgpct_series = eff_rows[f"fg_pct_{zone}"].ewm(halflife=EMA_HALFLIFE_SLOW, min_periods=1).mean()
            features[f"fgpct_avg10_{zone}"] = float(fgpct_series.iloc[-1])
        else:
            features[f"fgpct_avg10_{zone}"] = float("nan")

        defense_share = defense_snapshot.get(f"defense_share_allowed_avg_{zone}", float("nan"))
        defense_fg_pct = defense_snapshot.get(f"defense_fgpct_allowed_avg_{zone}", float("nan"))
        features[f"defense_share_allowed_avg_{zone}"] = defense_share
        features[f"defense_fgpct_allowed_avg_{zone}"] = defense_fg_pct

    return pd.DataFrame([features])


def fill_missing_features_with_league_average(bundle: ZoneModelBundle, row: pd.DataFrame) -> pd.DataFrame:
    """Substitui `NaN` (zona nunca vista pelo jogador, ou adversário sem
    amostra numa zona) pela média da liga guardada no bundle — os modelos
    (`StandardScaler` + `Ridge`) não aceitam `NaN` na entrada."""
    filled = row.copy()
    for zone in ZONES:
        filled[f"share_avg10_{zone}"] = filled[f"share_avg10_{zone}"].fillna(
            bundle.league_avg_share[zone]
        )
        filled[f"fgpct_avg10_{zone}"] = filled[f"fgpct_avg10_{zone}"].fillna(
            bundle.league_avg_fg_pct[zone]
        )
        filled[f"defense_share_allowed_avg_{zone}"] = filled[
            f"defense_share_allowed_avg_{zone}"
        ].fillna(bundle.league_avg_share[zone])
        filled[f"defense_fgpct_allowed_avg_{zone}"] = filled[
            f"defense_fgpct_allowed_avg_{zone}"
        ].fillna(bundle.league_avg_fg_pct[zone])
    return filled
