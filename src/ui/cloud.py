"""Elementos de interface da versão online (somente leitura).

Tudo aqui só age com ``NBA_DEPLOY_MODE=cloud``; no modo local os botões e
uploads funcionam exatamente como antes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd
import streamlit as st

from src import cloud_bootstrap
from src.cloud_bootstrap import BundleStatus
from src.deploy_mode import READ_ONLY_NOTICE, is_cloud

from .formatters import format_datetime_br


@st.cache_resource(ttl=cloud_bootstrap.CHECK_INTERVAL_SECONDS, show_spinner=False)
def _synchronized_status() -> BundleStatus:
    """Consulta o Release no máximo uma vez por hora por processo do servidor."""
    return cloud_bootstrap.sync_bundle()


def ensure_cloud_data() -> BundleStatus | None:
    """Garante o banco da nuvem antes de qualquer leitura. Sem modo nuvem não faz nada."""
    if not is_cloud():
        return None
    if cloud_bootstrap.has_local_data():
        status = _synchronized_status()
    else:
        with st.status("Preparando os dados pela primeira vez. Isso leva alguns instantes…") as box:
            status = _synchronized_status()
            if status.has_data:
                box.update(label="Dados prontos.", state="complete", expanded=False)
            else:
                box.update(label="Não foi possível preparar os dados.", state="error")
    if not status.has_data:
        _synchronized_status.clear()  # a próxima abertura tenta de novo, em vez de repetir a falha por 1 h
        st.error(
            "Os dados ainda não estão disponíveis. Tente novamente em alguns minutos; "
            "se persistir, o pacote de dados pode não ter sido publicado."
        )
        if status.error:
            st.caption(status.error)
        st.stop()
    if status.state == cloud_bootstrap.STATE_OFFLINE:
        st.warning(f"Não foi possível checar atualizações agora. Exibindo dados de {_version_label(status)}.")
    return status


def _version_label(status: BundleStatus) -> str:
    return status.generated_at[:10] if status.generated_at else (status.version or "versão anterior")


def read_only_mode() -> bool:
    return is_cloud()


def read_only_notice() -> None:
    """Aviso padrão para recursos que gravam ou consultam fontes externas."""
    st.caption(f":material/lock: {READ_ONLY_NOTICE}")


def action_button(label: str, **kwargs: Any) -> bool:
    """``st.button`` para ações que gravam dados ou chamam fontes externas.

    No modo nuvem aparece desabilitado, com a dica "somente leitura", e nunca
    retorna verdadeiro. Fora da nuvem é um ``st.button`` comum.
    """
    if not is_cloud():
        return st.button(label, **kwargs)
    kwargs.pop("on_click", None)
    kwargs.pop("args", None)
    kwargs["disabled"] = True
    kwargs["help"] = READ_ONLY_NOTICE
    st.button(label, **kwargs)
    return False


def action_file_uploader(label: str, **kwargs: Any) -> Any:
    """``st.file_uploader`` que, na nuvem, não aceita arquivos (importação grava no banco)."""
    if not is_cloud():
        return st.file_uploader(label, **kwargs)
    kwargs.pop("accept_multiple_files", None)
    kwargs["disabled"] = True
    kwargs["help"] = READ_ONLY_NOTICE
    st.file_uploader(label, **kwargs)
    return None


EXPERIMENTAL_NOTICE = (
    "Probabilidades experimentais, sem vantagem demonstrada sobre a referência simples; "
    "não são recomendação de aposta."
)


def _age_text(generated_at: str, now: datetime | None = None) -> str:
    """Idade legível (ex.: "3 h") de um carimbo ISO UTC; vazio se o carimbo for inválido."""
    try:
        moment = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = max(0, int(((now or datetime.now(UTC)) - moment).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} d"


def data_state() -> dict[str, str]:
    """Versão, data, idade e último erro dos dados publicados (para rodapé e Sistema)."""
    installed = cloud_bootstrap.read_installed_manifest()
    status = cloud_bootstrap.read_status()
    generated = installed.generated_at if installed else ""
    return {
        "version": installed.version if installed else "",
        "generated_at": generated,
        "age": _age_text(generated) if generated else "",
        "checked_at": status.checked_at if status else "",
        "error": status.error if status else "",
        "state": status.state if status else "",
    }


def _generated_label(info: dict[str, str]) -> str:
    return format_datetime_br(pd.Timestamp(info["generated_at"]).tz_convert("America/Sao_Paulo"))


def render_sidebar_notice() -> None:
    """Rodapé da barra lateral na versão online: versão dos dados, data e aviso de uso."""
    if not is_cloud():
        return
    info = data_state()
    with st.sidebar:
        st.divider()
        if info["generated_at"]:
            st.caption(f"Dados v{info['version']} · atualizados em {_generated_label(info)} (Brasília)")
        else:
            st.caption("Dados: versão não identificada")
        st.caption(EXPERIMENTAL_NOTICE)


def render_system_state() -> None:
    """Bloco "Dados da versão online" da página Sistema."""
    if not is_cloud():
        return
    info = data_state()
    st.subheader("Dados da versão online")
    first, second, third = st.columns(3)
    first.metric("Versão dos dados", info["version"] or "—")
    second.metric("Atualizados há", info["age"] or "—")
    third.metric(
        "Última checagem",
        format_datetime_br(pd.Timestamp(info["checked_at"]).tz_convert("America/Sao_Paulo"))
        if info["checked_at"]
        else "—",
    )
    if info["generated_at"]:
        st.caption(f"Pacote gerado em {_generated_label(info)} (Brasília).")
    if info["error"]:
        st.warning(f"Último erro ao buscar atualização: {info['error']}")
    else:
        st.caption("Sem erros na última checagem.")
    st.caption(READ_ONLY_NOTICE)
