import numpy as np
import pandas as pd
import pytest

from src.prop_training import _fit_props, feature_table, project_props
from src.prop_validation import clustered_interval, frozen_predictions, temporal_audit
from tests.test_analysis_archive import research_history as research_history


def test_game_cluster_interval_preserves_shared_game_errors():
    values = pd.Series([1.0] * 20 + [-1.0] * 20)
    interval = clustered_interval(values, pd.Series(["a"] * 20 + ["b"] * 20))
    assert interval == dict(mean=0, low=-1, high=1, games=2)
    assert clustered_interval(pd.Series(dtype=float), pd.Series(dtype=str))["mean"] is None


def test_external_audit_never_trains_inside_its_test_window(research_history):
    calls = []

    def fit(before):
        calls.append(before.game_date.max())
        return _fit_props(before, estimators=5)

    report, rows = temporal_audit(research_history, trainer=fit, folds=1, test_dates=5)
    assert len(report["windows"]) == len(calls) == 1
    assert report["windows"][0]["train_end"] < rows.day.min()
    assert report["independent"] and not rows.empty
    assert not rows.duplicated(["game", "player_id", "stat"]).any()
    assert rows.groupby("stat").size().nunique() == 1
    for stat in ("pts", "reb", "ast"):
        assert report["stats"][stat]["status"] == "Amostra insuficiente"


def test_batch_audit_matches_actual_projection_distribution(research_history):
    dates = sorted(research_history.game_date.unique())
    before = research_history.loc[research_history.game_date.lt(dates[-5])]
    bundle = _fit_props(before, estimators=5)
    table = feature_table(research_history)
    row = table.loc[table.game_date.eq(dates[-1]) & table.history_games.ge(5)].iloc[[0]]
    actual = project_props(row.iloc[0], bundle)
    batch = frozen_predictions(row, bundle, fold=1)
    for item in batch.itertuples(index=False):
        for key in ("projected", "over", "under", "low", "high", "dispersion_shape"):
            assert getattr(item, key) == pytest.approx(actual["stats"][item.stat][key], rel=1e-5)
    assert np.isfinite(batch.projected).all()
