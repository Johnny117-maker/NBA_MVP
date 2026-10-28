"""Métricas reproduzíveis; indicadores de terceiros mantêm nome e procedência próprios."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import beta
from sklearn.linear_model import Ridge


def beta_shooting(made: float, attempted: float, prior_mean: float, strength: float = 50) -> dict:
    """Posterior Beta-Binomial: a força do prior representa tentativas equivalentes."""
    if not all(math.isfinite(v) for v in (made, attempted, prior_mean, strength)):
        raise ValueError("Parâmetros de arremesso devem ser finitos.")
    if made < 0 or attempted < made or not 0 < prior_mean < 1 or strength <= 0:
        raise ValueError("Conversões, tentativas ou prior inválidos.")
    alpha = prior_mean * strength + made
    other = (1 - prior_mean) * strength + attempted - made
    distribution = beta(alpha, other)
    return {
        "mean": float(distribution.mean()),
        "low": float(distribution.ppf(0.1)),
        "high": float(distribution.ppf(0.9)),
        "attempts": attempted,
        "prior_strength": strength,
    }


def kalman_rate(counts, exposure) -> dict:
    """Filtro local em log(taxa/minuto), com ruído de observação dependente da amostra.

    Não reproduz DARKO/DPM. Usa apenas os jogos fornecidos, em ordem cronológica.
    """
    values = [(float(y), float(m)) for y, m in zip(counts, exposure, strict=True) if m > 0]
    if not values or any(not math.isfinite(y + m) or y < 0 for y, m in values):
        raise ValueError("São necessárias contagens não negativas e minutos válidos.")
    mean = math.log((values[0][0] + 0.5) / (values[0][1] + 1))
    variance = 1.0
    for count, minutes in values:
        variance += 0.015
        observation = math.log((count + 0.5) / (minutes + 1))
        noise = 1 / (count + 0.5)
        gain = variance / (variance + noise)
        mean += gain * (observation - mean)
        variance *= 1 - gain
    return {
        "rate": math.exp(mean + variance / 2),
        "low_rate": math.exp(mean - 1.2815516 * math.sqrt(variance)),
        "high_rate": math.exp(mean + 1.2815516 * math.sqrt(variance)),
        "log_variance": variance,
        "games": len(values),
    }


@dataclass
class RapmResult:
    ratings: pd.DataFrame
    alpha: float
    stints: int
    possessions: float


def fit_rapm(stints: pd.DataFrame, alpha: float = 2000) -> RapmResult:
    """Ridge por 100 posses, ponderado pelo número de posses de cada stint.

    Contrato: home_players/away_players são listas JSON com 5 IDs NBA distintos;
    points_diff é o saldo DAQUELE stint, possessions é a exposição medida.
    A penalidade é explícita, sem alegar que foi calibrada para esta base.
    """
    required = {"home_players", "away_players", "points_diff", "possessions"}
    if not required.issubset(stints) or stints.empty or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("Informe stints completos e regularização positiva.")
    lineups = []
    for row in stints.to_dict("records"):
        home = (
            json.loads(row["home_players"]) if isinstance(row["home_players"], str) else row["home_players"]
        )
        away = (
            json.loads(row["away_players"]) if isinstance(row["away_players"], str) else row["away_players"]
        )
        both = [*home, *away]
        if (
            len(home) != 5
            or len(away) != 5
            or len(set(both)) != 10
            or any(not isinstance(p, int) or isinstance(p, bool) or p <= 0 for p in both)
        ):
            raise ValueError("Cada stint exige dez IDs oficiais distintos, cinco por equipe.")
        lineups.append((home, away))
    possessions = pd.to_numeric(stints["possessions"], errors="coerce").to_numpy(dtype=float)
    points = pd.to_numeric(stints["points_diff"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(possessions).all() or (possessions <= 0).any() or not np.isfinite(points).all():
        raise ValueError("Posses devem ser positivas e saldos devem ser finitos.")
    players = sorted({pid for home, away in lineups for pid in [*home, *away]})
    indexes = {pid: i for i, pid in enumerate(players)}
    rows, columns, values = [], [], []
    for i, (home, away) in enumerate(lineups):
        for ids, sign in ((home, 1.0), (away, -1.0)):
            for pid in ids:
                rows.append(i)
                columns.append(indexes[pid])
                values.append(sign)
    matrix = sparse.csr_matrix((values, (rows, columns)), shape=(len(stints), len(players)))
    model = Ridge(alpha=alpha, fit_intercept=True, solver="lsqr")
    model.fit(matrix, 100 * points / possessions, sample_weight=possessions)
    exposure = np.asarray(abs(matrix).T @ possessions).ravel()
    ratings = pd.DataFrame({"player_id": players, "rapm": model.coef_, "possessions": exposure})
    return RapmResult(ratings.sort_values("rapm", ascending=False), alpha, len(stints), possessions.sum())


def defended_rim(made: float, attempted: float, normal_pct: float | None = None) -> dict:
    if not math.isfinite(made + attempted) or made < 0 or attempted < made:
        raise ValueError("Tentativas defendidas inválidas.")
    if normal_pct is not None and (not math.isfinite(normal_pct) or not 0 <= normal_pct <= 1):
        raise ValueError("A eficiência de referência deve estar entre 0 e 1.")
    pct = made / attempted if attempted > 0 else None
    return {
        "dfg_pct": pct,
        "attempts": attempted,
        "diff_pct": pct - normal_pct if pct is not None and normal_pct is not None else None,
    }


def off_ball_gravity(frames: pd.DataFrame) -> pd.DataFrame:
    """Indicador LOCAL de aproximação defensiva, em pés, sem alegar padrão oficial.

    Um registro por frame/jogador com defensor atribuído e distância esperada de
    referência, obtida de tracking externo. Distância menor que a referência = atração.
    Não infere tracking a partir de pontos, bolas de três ou coordenadas de arremesso.
    """
    columns = ["x", "y", "defender_x", "defender_y", "baseline_distance", "duration"]
    required = {"frame_id", "player_id", "ball_handler_id", *columns}
    if not required.issubset(frames) or frames.empty:
        raise ValueError("Gravity exige tracking, defensor atribuído, referência e duração de cada frame.")
    values = frames[columns].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(values.to_numpy()).all()
        or values["duration"].le(0).any()
        or values["baseline_distance"].lt(0).any()
        or frames.duplicated(["frame_id", "player_id"]).any()
    ):
        raise ValueError("Frames inválidos ou duplicados.")
    data = frames.loc[frames["player_id"].ne(frames["ball_handler_id"])].copy()
    values = values.loc[data.index]
    distance = np.hypot(values["x"] - values["defender_x"], values["y"] - values["defender_y"])
    data["weighted_pull"] = (values["baseline_distance"] - distance) * values["duration"]
    data["duration"] = values["duration"]
    result = data.groupby("player_id", as_index=False).agg(
        weighted_pull=("weighted_pull", "sum"), seconds=("duration", "sum"), frames=("frame_id", "count")
    )
    result["gravity_local_ft"] = result["weighted_pull"] / result["seconds"]
    return result.drop(columns="weighted_pull")
