from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from .formatters import format_datetime_br, format_int_br

_VALID_NOTE_KINDS = {"info", "warning", "danger", "success"}

# "no máximo seis indicadores por linha" (seção 16.1) — itens extras quebram
# para a linha seguinte automaticamente.
MAX_METRICS_PER_ROW = 6

SMALL_SAMPLE_THRESHOLD = 15
MODERATE_SAMPLE_THRESHOLD = 40


def note(text: str, kind: str = "info") -> None:
    """Caixa de aviso com borda colorida por tipo (seção 5/13 do planejamento de UI/UX).

    Substitui os `<div class="note">...` inline que antes eram copiados e
    colados em `app.py`/`pages/1_Jogadores.py` — mesma aparência, uma
    definição só (`src/ui/theme.py`).
    """
    if kind not in _VALID_NOTE_KINDS:
        raise ValueError(f"kind inválido: {kind!r}. Use um de {sorted(_VALID_NOTE_KINDS)}.")
    st.markdown(f'<div class="app-note app-note--{kind}">{escape(text)}</div>', unsafe_allow_html=True)


def page_header(title: str, description: str, category: str = "EXPLORAR", *, hero: bool = False) -> None:
    heading_class = "page-heading page-heading--hero" if hero else "page-heading"
    illustration = (
        '<svg class="hero-art" viewBox="0 0 200 200" fill="none" aria-hidden="true">'
        '<path d="M65 25h70v45a35 35 0 0 1-70 0V25ZM65 35H30v20q0 40 40 40'
        'M135 35h35v20q0 40-40 40M100 105v40M65 170h70M80 145h40v25H80z" '
        'stroke="currentColor" stroke-width="10" stroke-linejoin="round"/></svg>' if hero else ""
    )
    st.markdown(
        f'<div class="{heading_class}">{illustration}'
        f'<div class="page-eyebrow">NBA ANALYTICS LAB / {escape(category)}</div>'
        f"<h1>{escape(title)}</h1><p>{escape(description)}</p></div>",
        unsafe_allow_html=True,
    )


def section_header(title: str, description: str = "") -> None:
    st.markdown(
        f'<div class="section-heading"><h2>{escape(title)}</h2><p>{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def tool_card(page_id: str) -> None:
    from .navigation import PAGE_BY_ID, page_link

    page = PAGE_BY_ID[page_id]
    with st.container(border=True):
        st.markdown(f"{page.icon} **{page.label}**")
        st.caption(page.description)
        page_link(page_id, label=f"Abrir {page.label.lower()}")


def load_on_demand(label: str, key: str, description: str) -> bool:
    """Mantém análises caras fora da abertura inicial; preserva a ativação na sessão."""
    if st.session_state.get(key, False):
        return True
    st.info(description)
    if st.button(label, key=f"{key}_activate", type="primary"):
        st.session_state[key] = True
        return True
    return False


def db_last_updated(path: Path) -> datetime | None:
    """Data da última escrita bem-sucedida no banco (proxy de "quando os dados
    foram atualizados"): a data de modificação do arquivo SQLite. Não é um
    timestamp exato de coleta guardado explicitamente — é uma aproximação
    simples, no mesmo espírito das outras aproximações já documentadas no
    projeto (ex.: Rating oficial por pontos antes da coleta chegar).
    """
    path = Path(path)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime)


def source_badge(
    source_label: str,
    updated_at: datetime | pd.Timestamp | None,
    seasons: str | None = None,
) -> None:
    """Selo de fonte e atualização (seção 5): "Fonte: X · Atualizado em ... · Temporadas: Y".

    `updated_at=None` omite o trecho de data — a base demonstrativa não tem
    uma data de coleta real para mostrar.
    """
    parts = [f"Fonte: {source_label}"]
    if updated_at is not None:
        parts.append(f"Atualizado em {format_datetime_br(updated_at)}")
    if seasons:
        parts.append(f"Temporadas: {seasons}")
    demo = " source-badge--demo" if "demonstra" in source_label.casefold() else ""
    st.markdown(f'<div class="source-badge{demo}">{escape(" · ".join(parts))}</div>', unsafe_allow_html=True)


def metric_row(items: list[dict]) -> None:
    """Cartões de indicadores padronizados (seção 16.1 do planejamento de UI/UX).

    Cada item: `{"label": str, "value": str, "delta": str opcional, "help": str opcional}`.
    Mais de `MAX_METRICS_PER_ROW` itens quebram em várias linhas de `st.columns`
    em vez de espremer tudo numa linha só.
    """
    for start in range(0, len(items), MAX_METRICS_PER_ROW):
        chunk = items[start : start + MAX_METRICS_PER_ROW]
        columns = st.columns(len(chunk))
        for column, item in zip(columns, chunk, strict=True):
            column.metric(item["label"], item["value"], item.get("delta"), help=item.get("help"))


def sample_size_caption(shown: int, total: int, unit: str = "partidas") -> None:
    """ "Exibindo X de Y partidas · Amostra {pequena/moderada/grande}" (seção 7.1)."""
    if shown <= SMALL_SAMPLE_THRESHOLD:
        label = "pequena"
    elif shown <= MODERATE_SAMPLE_THRESHOLD:
        label = "moderada"
    else:
        label = "grande"
    st.caption(f"Exibindo {format_int_br(shown)} de {format_int_br(total)} {unit} · Amostra {label}")


def clear_filters_button(keys: list[str], label: str = "Limpar filtros") -> None:
    """Botão que remove os widgets de filtro informados (por `key`) do
    `st.session_state` e recarrega a página — cada widget volta ao seu valor
    padrão declarado (seção 7.2: "oferecer um botão Limpar filtros").
    """
    if st.button(label):
        for key in keys:
            st.session_state.pop(key, None)
        st.rerun()


def persistent_selectbox(
    label: str, options: list[str], query_key: str, default_index: int = 0, **kwargs
) -> str:
    """`st.selectbox` cujo valor escolhido fica salvo num parâmetro da URL
    (seção "salvar preferências de filtros" do planejamento de UI/UX):
    recarregar a página ou compartilhar o link mantém a mesma seleção, em vez
    de voltar sempre para a primeira opção.

    Se o valor salvo na URL não existir mais em `options` (base mudou, opção
    saiu de cena), cai de volta em `default_index` silenciosamente — nunca
    quebra por causa de uma URL desatualizada.
    """
    if not options:
        raise ValueError("options não pode ser vazio.")
    saved_value = st.query_params.get(query_key)
    index = options.index(saved_value) if saved_value in options else default_index
    selected = st.selectbox(label, options, index=index, **kwargs)
    st.query_params[query_key] = selected
    return selected
