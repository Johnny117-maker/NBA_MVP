"""Qualidade das fontes é separada da probabilidade dos palpites."""

from __future__ import annotations

import pandas as pd

from .live_types import EASTERN, utc_now


def bulletin_quality(state: dict, now=None) -> dict:
    moment = pd.Timestamp(now or utc_now())
    if not state.get("source"):
        return dict(
            level="blocked", label="Boletim indisponível", reason="Aguardando uma fonte válida de lesões"
        )
    updated = pd.to_datetime(state.get("source_updated"), utc=True, errors="coerce")
    reference = pd.to_datetime(state.get("source_as_of"), utc=True, errors="coerce")
    age = None if pd.isna(updated) else max(0, (moment - updated).total_seconds() / 3600)
    reference_days = (
        None if pd.isna(reference) else (moment.tz_convert(EASTERN).date() - reference.date()).days
    )
    if (age is not None and age > 48) or (reference_days is not None and reference_days > 2):
        return dict(
            level="blocked",
            label="Boletim antigo",
            reason="Mais de 48 horas sem atualização ou referência antiga",
        )
    if state.get("stale") or age is None or reference_days is None:
        return dict(
            level="limited", label="Informação parcial", reason="Confira a referência e o horário do boletim"
        )
    return dict(level="current", label="Boletim recente", reason="Fonte e referência disponíveis")


def bulletin_usable(state: dict, now=None) -> bool:
    return bulletin_quality(state, now)["level"] != "blocked"


def collection_quality(status: dict, now=None) -> dict:
    moment = pd.Timestamp(now or utc_now())
    stamp = status.get("live_success_at") or status.get("archive_success_at")
    updated = pd.to_datetime(stamp, utc=True, errors="coerce")
    if pd.isna(updated):
        return dict(
            level="limited", label="Atualização pendente", reason="Sem horário de consulta confirmado"
        )
    age = max(0, (moment - updated).total_seconds() / 60)
    if age > 360:
        return dict(
            level="limited", label="Dados defasados", reason="Última consulta bem-sucedida há mais de 6 horas"
        )
    if not status.get("live_available") or age > 10:
        return dict(
            level="limited",
            label="Dados periódicos",
            reason="Sem confirmação de atualização ao vivo neste momento",
        )
    return dict(
        level="current", label="Coleta recente", reason="Fonte direta consultada nos últimos 10 minutos"
    )
