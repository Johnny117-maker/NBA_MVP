from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from .formatters import format_datetime_br


def empty_state(title: str, description: str, actions: list[tuple[str, str]] | None = None) -> None:
    """Banco vazio (seção 13.1 do planejamento de UI/UX): título curto + explicação
    + sugestões de ação em texto.

    Os botões de ação em si continuam sendo responsabilidade de quem chama
    (cada página sabe qual comando/link oferecer) — isto só padroniza a
    moldura visual. Sempre termina com `st.stop()`: nada depois desta chamada
    deveria rodar numa página sem dados.
    """
    st.info(f"**{title}**\n\n{description}")
    for label, detail in actions or []:
        st.caption(f"• **{label}** — {detail}")
    st.stop()


def error_state(message: str, detail: str | None = None) -> None:
    """Erro na fonte de dados (seção 13.3): o que falhou, com detalhe técnico opcional."""
    st.error(message if detail is None else f"{message}\n\n`{detail}`")


def small_sample_warning(count: int, threshold: int = 15, unit: str = "jogos") -> None:
    """Amostra pequena (seção 13.4): "Apenas N jogos correspondem aos filtros...".

    Só emite o aviso quando `count <= threshold` — chamada segura mesmo
    quando a amostra já é grande.
    """
    if count <= threshold:
        st.warning(
            f"Apenas {count} {unit} correspondem aos filtros. "
            "A projeção pode variar mais do que o normal."
        )


def stale_data_notice(last_updated: datetime | pd.Timestamp | None, days_threshold: int = 7) -> None:
    """Dados desatualizados (seção 13.5): avisa quando a última atualização passou
    de `days_threshold` dias.

    Silencioso quando `last_updated` é `None` (base sem data de coleta
    conhecida, ex.: demonstrativa).
    """
    if last_updated is None:
        return
    age_days = (pd.Timestamp.now() - pd.Timestamp(last_updated)).days
    if age_days > days_threshold:
        st.warning(
            f"Os dados foram atualizados há {age_days} dias "
            f"({format_datetime_br(last_updated)}). Alguns jogos recentes podem não estar incluídos."
        )
