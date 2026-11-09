"""Elementos de interface da versão online (somente leitura).

Tudo aqui só age com ``NBA_DEPLOY_MODE=cloud``; no modo local os botões e
uploads funcionam exatamente como antes.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from src import cloud_bootstrap
from src.cloud_bootstrap import BundleStatus
from src.deploy_mode import READ_ONLY_NOTICE, is_cloud


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
