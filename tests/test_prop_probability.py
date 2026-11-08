import numpy as np
import pandas as pd
import pytest

from src.forecast_performance import probability_metrics, probability_rows
from src.prop_explanations import compare_line
from src.prop_probability import fit_dispersion


@pytest.mark.parametrize("mean", [0, 0.1, 20, 80])
@pytest.mark.parametrize("shape", [0.1, 1, 60])
def test_count_probabilities_sum_to_one_and_respect_line_order(mean, shape):
    estimate = dict(projected=mean, dispersion_shape=shape)
    values = [compare_line(estimate, line) for line in (0, 0.5, 5, 5.5, 20.5, 200)]
    assert all(sum(v.values()) == pytest.approx(1) for v in values)
    assert all(v["over"] >= following["over"] for v, following in zip(values, values[1:], strict=False))
    if mean == 0:
        assert values[0] == dict(over=0, under=0, push=1)
        assert values[1] == dict(over=0, under=1, push=0)


def test_under_is_not_counted_as_extra_independent_evidence():
    rows = pd.DataFrame(
        dict(actual=[10, 20, 12], line=[10.5, 19.5, 12.5], over=[0.2, 0.9, 0.3], under=[0.8, 0.1, 0.7])
    )
    assert probability_metrics(rows) == pytest.approx(probability_metrics(rows, side="under"))
    rows.loc[0, "under"] = 0.9
    rows["actual"] = rows["actual"].astype(float)  # evita atribuir 20.5 a uma coluna int64
    rows.loc[1, "actual"] = 20.5
    assert len(probability_rows(rows)) == 1


def test_dispersion_adjustment_needs_improvement_on_later_dates():
    rng = np.random.default_rng(42)

    def sample(counts, start):
        return pd.DataFrame(
            dict(
                pts=counts,
                expected_minutes=30,
                pts_bayes=20,
                pts_alpha=100,
                game_date=pd.date_range(start, periods=len(counts), freq="h").normalize(),
            )
        )

    calibration = sample(rng.poisson(20, 1000), "2025-01-01")
    validation = sample(rng.poisson(20, 1000), "2025-03-01")
    result = fit_dispersion(calibration, validation, np.full(1000, 20), np.full(1000, 20), 1, "pts")
    assert result["active"] and result["scale"] > 1
    validation.pts = rng.negative_binomial(0.1, 0.1 / 20.1, 1000)
    rejected = fit_dispersion(calibration, validation, np.full(1000, 20), np.full(1000, 20), 1, "pts")
    assert not rejected["active"] and rejected["scale"] == 1
