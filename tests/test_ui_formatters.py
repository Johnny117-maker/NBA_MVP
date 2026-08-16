import pandas as pd

from src.ui.formatters import (
    format_date_br,
    format_datetime_br,
    format_decimal_br,
    format_int_br,
    format_pct_br,
)


def test_format_int_br_uses_period_as_thousands_separator():
    assert format_int_br(12345) == "12.345"
    assert format_int_br(1230) == "1.230"
    assert format_int_br(999) == "999"


def test_format_decimal_br_uses_comma_as_decimal_separator():
    assert format_decimal_br(23.8) == "23,8"
    assert format_decimal_br(1234.5) == "1.234,5"
    assert format_decimal_br(5, decimals=2) == "5,00"


def test_format_pct_br_converts_fraction_to_percentage_with_comma():
    assert format_pct_br(0.475) == "47,5%"
    assert format_pct_br(1.0) == "100,0%"
    assert format_pct_br(0.0) == "0,0%"


def test_format_date_br_returns_ddmmyyyy():
    assert format_date_br(pd.Timestamp("2026-08-16")) == "16/08/2026"
    assert format_date_br("2026-01-05") == "05/01/2026"


def test_format_datetime_br_includes_time():
    assert format_datetime_br(pd.Timestamp("2026-08-16 14:30")) == "16/08/2026 às 14:30"
