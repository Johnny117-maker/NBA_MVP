"""Teste externo à seleção dos modelos, com previsões congeladas por janela temporal."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from .forecast_performance import calibration_bins, probability_metrics, quantity_metrics
from .live_types import utc_now
from .minutes_model import MINUTE_FEATURES, minutes_ratio
from .prop_training import STATS, VERSION, PropsBundle, feature_table

AUDIT_VERSION = "props-independent-audit-v1"


def clustered_interval(values: pd.Series, games: pd.Series, *, draws: int = 1000) -> dict:
    """IC percentil pareado: atletas da mesma partida nunca são reamostrados separadamente."""
    table = pd.DataFrame({"value": values, "game": games}).dropna()
    if table.empty:
        return dict(mean=None, low=None, high=None, games=0)
    grouped = table.groupby("game").value.agg(["sum", "count"])
    if len(grouped) < 2:
        return dict(mean=float(table.value.mean()), low=None, high=None, games=len(grouped))
    rng = np.random.default_rng(42)
    samples = rng.integers(0, len(grouped), size=(draws, len(grouped)))
    means = grouped["sum"].to_numpy()[samples].sum(axis=1) / grouped["count"].to_numpy()[samples].sum(axis=1)
    return dict(
        mean=float(table.value.mean()),
        low=float(np.quantile(means, 0.025)),
        high=float(np.quantile(means, 0.975)),
        games=len(grouped),
    )


def frozen_predictions(table: pd.DataFrame, bundle: PropsBundle, *, fold: int) -> pd.DataFrame:
    """Usa o mesmo ajuste de minutos e distribuição da projeção, sem treinar no bloco avaliado."""
    baseline_minutes = table.expected_minutes.to_numpy()
    minutes = np.clip(baseline_minutes, 1, 48)
    report = bundle.manifest.get("minutes_model", {})
    if bundle.minutes_model is not None and report.get("active"):
        candidate = np.clip(bundle.minutes_model.predict(table[MINUTE_FEATURES].astype(float)), 1, 48)
        minutes = np.clip((1 - report["weight"]) * baseline_minutes + report["weight"] * candidate, 1, 48)
    ratio = minutes_ratio(minutes, baseline_minutes)
    records = []
    for stat in STATS:
        bayes = table[f"{stat}_bayes"].to_numpy() * ratio
        ml = bundle.predict(table, stat) * ratio
        weight = bundle.manifest["weights"][stat]
        mean = (1 - weight) * bayes + weight * ml
        shape = 1 / (1 / bundle.manifest["dispersion"][stat] + 1 / table[f"{stat}_alpha"].to_numpy())
        distribution = nbinom(shape, shape / (shape + np.maximum(mean, 0.001)))
        line = np.floor(bayes) + 0.5
        records.append(
            pd.DataFrame(
                dict(
                    fold=fold,
                    day=table.game_date.dt.strftime("%Y-%m-%d"),
                    game=table.game_id.astype(str),
                    player=table.player_name,
                    player_id=table.player_id,
                    season=table.season,
                    stat=stat,
                    actual=table[stat],
                    projected=mean,
                    reference=table[f"{stat}_mean10"],
                    bayes=bayes,
                    xgboost=ml,
                    low=distribution.ppf(0.1),
                    high=distribution.ppf(0.9),
                    line=line,
                    over=distribution.sf(np.floor(line)),
                    under=distribution.cdf(np.floor(line)),
                    minutes=minutes,
                    actual_minutes=table.minutes,
                    dispersion_shape=shape,
                )
            )
        )
    return pd.concat(records, ignore_index=True)


def evidence_summary(rows: pd.DataFrame) -> dict:
    result = {}
    for stat in STATS:
        selected = rows.loc[rows.stat.eq(stat)].copy() if not rows.empty else rows
        metrics = quantity_metrics(selected)
        if not metrics["n"]:
            result[stat] = dict(status="Amostra insuficiente", n=0)
            continue
        gain = (selected.reference - selected.actual).abs() - (selected.projected - selected.actual).abs()
        interval = clustered_interval(gain, selected.game)
        enough = metrics["n"] >= 500 and interval["games"] >= 30 and selected.day.nunique() >= 14
        favorable = (
            enough
            and interval["low"] is not None
            and interval["low"] > 0
            and interval["mean"] >= float((selected.reference - selected.actual).abs().mean()) * 0.02
        )
        probabilities = probability_metrics(selected)
        loss = (selected.over - selected.actual.gt(selected.line).astype(float)) ** 2
        probability_gain = clustered_interval(0.25 - loss, selected.game)
        reference_loss = (selected.reference_over - selected.actual.gt(selected.line).astype(float)) ** 2
        reference_brier = float(reference_loss.mean())
        result[stat] = dict(
            **metrics,
            dates=int(selected.day.nunique()),
            games=interval["games"],
            reference_mae=float((selected.reference - selected.actual).abs().mean()),
            improvement=interval,
            status="Evidência histórica favorável"
            if favorable
            else ("Sem vantagem demonstrada" if enough else "Amostra insuficiente"),
            probability=probabilities,
            probability_gain_vs_50=probability_gain,
            reference_probability_brier=reference_brier,
            probability_gain_vs_reference=clustered_interval(reference_loss - loss, selected.game),
            brier_skill=1 - float(loss.mean()) / reference_brier if reference_brier > 0 else None,
            calibration=calibration_bins(selected).to_dict("records"),
            by_season=[
                dict(season=season, **quantity_metrics(group)) for season, group in selected.groupby("season")
            ],
        )
    return result


def temporal_audit(
    history: pd.DataFrame,
    *,
    trainer: Callable[[pd.DataFrame], PropsBundle] | None = None,
    folds: int = 2,
    test_dates: int = 14,
) -> tuple[dict, pd.DataFrame]:
    if folds < 1 or test_dates < 1:
        raise ValueError("O número de janelas e datas deve ser positivo.")
    if trainer is None:
        from .prop_training import _fit_props

        trainer = _fit_props
    table = feature_table(history)
    eligible = table.loc[table.history_games.ge(5) & table.expected_minutes.ge(10)].copy()
    dates = sorted(eligible.game_date.unique())
    fingerprint = hashlib.sha256(
        (AUDIT_VERSION + VERSION + str((folds, test_dates))).encode()
        + pd.util.hash_pandas_object(history, index=False).values.tobytes()
    ).hexdigest()
    report: dict = dict(
        version=AUDIT_VERSION,
        policy=VERSION,
        id=f"{AUDIT_VERSION}-{fingerprint[:16]}",
        data_hash=fingerprint,
        checked_at=utc_now().isoformat(),
        windows=[],
        stats={},
        status="Amostra insuficiente",
        independent=True,
        scope="Histórico reconstruído; não é captura pré-jogo nem teste de odds de casas",
        protocol="Treino e seleção terminam antes de cada janela externa; modelo congelado nessa janela. "
        "A forma usa somente partidas anteriores a cada previsão. Avaliação condicionada à participação.",
        uncertainty="Bootstrap pareado por partida, 1.000 reamostragens, IC de 95%. "
        "A dependência entre partidas do mesmo atleta pode permanecer.",
        limits="Sem boletins históricos de lesões, escalações confirmadas ou linhas de casas. "
        "Resultados agregados não comprovam qualidade para um atleta específico ou lucro.",
    )
    records = []
    for index in range(folds):
        start_index = len(dates) - (folds - index) * test_dates
        if start_index < 20:
            continue
        start = pd.Timestamp(dates[start_index])
        stop_index = min(start_index + test_dates, len(dates))
        stop = pd.Timestamp(dates[stop_index - 1])
        before = history.loc[pd.to_datetime(history.game_date).lt(start)].copy()
        fit_eligible = table.loc[table.game_date.lt(start) & table.history_games.ge(5)]
        if len(fit_eligible) < 1000 or fit_eligible.game_date.nunique() < 20:
            continue
        bundle = trainer(before)
        if pd.Timestamp(bundle.manifest["train_end"]) >= start:
            raise ValueError("O modelo alcança o período externo de avaliação.")
        test = eligible.loc[eligible.game_date.between(start, stop)]
        predictions = frozen_predictions(test, bundle, fold=index + 1)
        priors = {}
        for stat in STATS:
            reference_rows = fit_eligible.loc[fit_eligible.expected_minutes.ge(10)]
            successes = reference_rows[stat].gt(np.floor(reference_rows[f"{stat}_bayes"]) + 0.5).sum()
            priors[stat] = float((successes + 0.5) / (len(reference_rows) + 1))
        predictions["reference_over"] = predictions.stat.map(priors)
        records.append(predictions)
        report["windows"].append(
            dict(
                fold=index + 1,
                train_end=bundle.manifest["train_end"],
                start=start.date().isoformat(),
                end=stop.date().isoformat(),
                player_games=len(test),
                games=int(test.game_id.nunique()),
                weights=bundle.manifest["weights"],
                minutes_active=bundle.manifest["minutes_model"]["active"],
            )
        )
    rows = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    if not rows.empty:
        if rows.duplicated(["game", "player_id", "stat"]).any():
            raise ValueError("Janelas sobrepostas ou observações duplicadas no teste externo.")
        report.update(
            status="Teste histórico independente concluído",
            stats=evidence_summary(rows),
            start=str(rows.day.min()),
            end=str(rows.day.max()),
            player_games=len(rows) // 3,
        )
    return report, rows
