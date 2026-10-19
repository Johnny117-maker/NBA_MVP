from __future__ import annotations

from datetime import datetime

import pandas as pd

# Padrão brasileiro (seção 14 do planejamento de UI/UX): separador de milhar
# com ponto, decimal com vírgula, data dd/mm/aaaa. O resto do app hoje usa o
# padrão americano nas tabelas/gráficos já existentes (não mexido aqui) —
# estes formatadores valem para os componentes novos de `src/ui`.


def format_int_br(value: int | float) -> str:
    """Milhar com ponto: 12345 -> "12.345"."""
    return f"{int(round(value)):,}".replace(",", ".")


def format_decimal_br(value: float, decimals: int = 1) -> str:
    """Decimal com vírgula: 23.8 -> "23,8"."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "␟").replace(".", ",").replace("␟", ".")


def format_pct_br(value: float, decimals: int = 1) -> str:
    """Percentual com vírgula: 0.475 -> "47,5%" (`value` é fração, não já ×100)."""
    return f"{format_decimal_br(value * 100, decimals)}%"


def format_date_br(value: datetime | pd.Timestamp | str) -> str:
    """Data no formato brasileiro: dd/mm/aaaa."""
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%d/%m/%Y")


def format_datetime_br(value: datetime | pd.Timestamp | str) -> str:
    """Data e hora no formato brasileiro: dd/mm/aaaa às HH:MM."""
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%d/%m/%Y às %H:%M")
