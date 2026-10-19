import pandas as pd

from src.ui.explanations import explain_zone_shift


def _comparison_row(
    zone_label,
    attempts_a,
    attempts_b,
    frequency_a,
    frequency_b,
    fg_pct_a,
    fg_pct_b,
) -> dict:
    return {
        "shot_zone_basic": zone_label,
        "zone_label": zone_label,
        "attempts_a": attempts_a,
        "attempts_b": attempts_b,
        "frequency_a": frequency_a,
        "frequency_b": frequency_b,
        "fg_pct_a": fg_pct_a,
        "fg_pct_b": fg_pct_b,
        "points_per_shot_a": fg_pct_a * 2,
        "points_per_shot_b": fg_pct_b * 2,
    }


def test_explain_zone_shift_mentions_dominant_zone():
    comparison = pd.DataFrame(
        [
            _comparison_row("Aro", 50, 55, 0.55, 0.60, 0.60, 0.60),
            _comparison_row("Três", 30, 25, 0.33, 0.27, 0.35, 0.35),
        ]
    )
    text = explain_zone_shift(comparison)
    assert "concentra 60%" in text
    assert "aro" in text.lower()


def test_explain_zone_shift_flags_the_biggest_frequency_change():
    comparison = pd.DataFrame(
        [
            _comparison_row("Aro", 50, 50, 0.50, 0.50, 0.60, 0.60),
            _comparison_row("Três frontal", 20, 40, 0.20, 0.40, 0.35, 0.35),
        ]
    )
    text = explain_zone_shift(comparison, label_a="temporada anterior", label_b="temporada atual")
    assert "aumentou" in text
    assert "20 p.p." in text
    assert "três frontal" in text.lower()
    assert "temporada anterior" in text
    assert "temporada atual" in text


def test_explain_zone_shift_ignores_small_frequency_noise():
    comparison = pd.DataFrame(
        [
            _comparison_row("Aro", 50, 50, 0.50, 0.51, 0.60, 0.60),
            _comparison_row("Três", 30, 30, 0.30, 0.29, 0.35, 0.35),
        ]
    )
    text = explain_zone_shift(comparison)
    assert "aumentou" not in text
    assert "reduziu" not in text


def test_explain_zone_shift_flags_efficiency_change_when_sample_is_large_enough():
    comparison = pd.DataFrame(
        [
            _comparison_row("Aro", 40, 40, 0.60, 0.60, 0.55, 0.75),
            _comparison_row("Três", 20, 20, 0.40, 0.40, 0.35, 0.35),
        ]
    )
    text = explain_zone_shift(comparison)
    assert "melhorou" in text
    assert "20 p.p." in text
    assert "aproveitamento" in text


def test_explain_zone_shift_warns_when_sample_too_small_for_efficiency():
    comparison = pd.DataFrame(
        [
            _comparison_row("Aro", 3, 4, 0.60, 0.60, 0.55, 0.75),
            _comparison_row("Três", 2, 2, 0.40, 0.40, 0.35, 0.35),
        ]
    )
    text = explain_zone_shift(comparison, min_sample_attempts=15)
    assert "amostra ainda é pequena" in text
    assert "melhorou" not in text
    assert "piorou" not in text


def test_explain_zone_shift_empty_comparison_returns_fallback_message():
    assert "Sem arremessos suficientes" in explain_zone_shift(pd.DataFrame())


def test_explain_zone_shift_all_zero_attempts_returns_fallback_message():
    comparison = pd.DataFrame([_comparison_row("Aro", 0, 0, 0.0, 0.0, float("nan"), float("nan"))])
    assert "Sem arremessos suficientes" in explain_zone_shift(comparison)
