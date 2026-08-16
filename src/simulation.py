from __future__ import annotations

import numpy as np
import pandas as pd

from .model import GamePrediction


def simulate_score_distribution(
    prediction: GamePrediction,
    home_std: float,
    away_std: float,
    simulations: int = 5_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Simula placares apenas para visualização da incerteza do modelo."""
    rng = np.random.default_rng(seed)
    home_scores = np.maximum(
        0, np.rint(rng.normal(prediction.home_score, home_std, simulations))
    ).astype(int)
    away_scores = np.maximum(
        0, np.rint(rng.normal(prediction.away_score, away_std, simulations))
    ).astype(int)

    ties = home_scores == away_scores
    home_scores[ties] += rng.choice([1, 2, 3], size=int(ties.sum()))

    return pd.DataFrame(
        {
            "home_score": home_scores,
            "away_score": away_scores,
            "margin": home_scores - away_scores,
            "home_win": home_scores > away_scores,
        }
    )

