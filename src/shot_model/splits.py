"""Cortes temporais do modelo de zonas (sempre por data completa)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..model import temporal_split_index


def split_zone_games_by_date(ordered: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa ~80% / ~20% mantendo datas completas de um lado só.

    `ordered` precisa estar ordenado por `game_date`. Vários jogadores jogam na
    mesma data; cortar por posição de linha deixaria a mesma data no treino e
    no teste. Usa o mesmo critério dos modelos de times
    (`model.py::temporal_split_index`).
    """
    split = temporal_split_index(ordered)
    return ordered.iloc[:split], ordered.iloc[split:]


def walk_forward_boundaries(dates: pd.Series, n_folds: int, min_train_games: int) -> list[int]:
    """Posições de corte do walk-forward, sem repartir uma data entre dois folds.

    Cada corte intermediário avança até o fim da data da última linha de treino,
    de modo que o treino nunca fica menor que `min_train_games`. `dates` precisa
    estar ordenado.
    """
    values = pd.to_datetime(dates).dt.normalize().to_numpy()
    total = len(values)
    raw = np.linspace(min_train_games, total, n_folds + 1, dtype=int)
    return [
        total if cut >= total else int(np.searchsorted(values, values[cut - 1], side="right"))
        for cut in raw
    ]
