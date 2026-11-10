import json
import sys

import pandas as pd
import streamlit as st

from src.app_paths import state_root
from src.desktop_support import APP_VERSION
from src.desktop_updates import ArchiveError, UpdateError, activate_shortcut, check_update, prepare_update
from src.source_health import read_source_health
from src.store import DEFAULT_DB_PATH
from src.ui import components, theme
from src.ui.cloud import action_button, render_system_state

st.set_page_config(
    page_title="Sistema — NBA Analytics Lab", page_icon=":material/system_update:", layout="wide"
)
theme.inject_base_style("system")
components.page_header("Sistema e atualizações", "Atualize o programa preservando sua base e o histórico.")
render_system_state()
st.metric("Versão em uso", APP_VERSION)
frozen = bool(getattr(sys, "frozen", False))
if not frozen:
    st.caption("Modo de desenvolvimento. A preparação de pacotes é disponibilizada no executável Windows.")
if action_button("Buscar atualização do programa"):
    try:
        with st.spinner("Consultando a versão publicada…"):
            st.session_state["desktop_update"] = check_update()
    except (ArchiveError, UpdateError) as error:
        st.warning(str(error))
info = st.session_state.get("desktop_update")
if info:
    if info["status"] == "no_update":
        st.success("Não há uma versão estável mais recente publicada.")
    else:
        st.info(f"Versão {info['latest']} disponível · pacote do programa: {info['size'] / 1_000_000:.0f} MB")
        st.link_button("Ver informações da versão", info["url"])
        if action_button("Baixar e preparar atualização", type="primary", disabled=not frozen):
            try:
                with st.spinner("Baixando e conferindo o pacote. Você pode continuar usando a versão atual…"):
                    prepare_update(info, state_root())
                st.success("Atualização preparada em uma pasta separada. A versão atual foi preservada.")
            except (ArchiveError, UpdateError, OSError) as error:
                st.warning(str(error))
prepared = state_root() / "updates/last_prepared.json"
record = None
if prepared.exists():
    try:
        record = json.loads(prepared.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not {"version", "executable", "sha256"}.issubset(record):
            record = None
            st.warning("O registro da atualização preparada está incompleto. Prepare o pacote novamente.")
    except (OSError, ValueError):
        st.warning("Não foi possível ler o registro da atualização preparada.")
if record:
    st.subheader("Versão preparada: " + record["version"])
    st.caption("Atualize o atalho, feche a versão atual e abra novamente pelo ícone da Área de Trabalho.")
    if action_button("Usar a versão preparada no próximo início", disabled=not frozen):
        try:
            activate_shortcut(record["executable"])
            st.success("Atalho atualizado. Feche este sistema e abra novamente pelo ícone.")
        except UpdateError as error:
            st.warning(str(error))
    if record.get("previous_executable") and action_button(
        "Restaurar atalho da versão anterior", disabled=not frozen
    ):
        try:
            activate_shortcut(record["previous_executable"])
            st.success("Atalho anterior restaurado. Os dados pessoais não foram substituídos.")
        except UpdateError as error:
            st.warning(str(error))
    with st.expander("Local e verificação do pacote"):
        st.code(record["executable"], language=None)
        st.caption("SHA-256 conferido: " + record["sha256"])
st.subheader("Estado das fontes de dados")
health = read_source_health(DEFAULT_DB_PATH)
if not health:
    st.caption("Ainda não há consultas registradas nesta base. O estado aparece depois da primeira coleta.")
else:

    def _stamp(value: str | None) -> str:
        if not value:
            return "—"
        return pd.Timestamp(value).tz_convert("America/Sao_Paulo").strftime("%d/%m %H:%M")

    st.dataframe(
        pd.DataFrame(
            {
                "Fonte": list(health),
                "Última resposta OK": [_stamp(row.get("last_ok")) for row in health.values()],
                "Último erro": [_stamp(row.get("last_error")) for row in health.values()],
                "Tipo do erro": [row.get("last_error_type", "—") for row in health.values()],
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption("Horários de Brasília. Erro mais recente que a última resposta OK indica fonte instável.")
st.caption(
    "As estatísticas continuam sendo coletadas separadamente. "
    "O pacote de atualização não inclui a base histórica. "
    "O acesso ao repositório privado utiliza sua autenticação GitHub local ou o token de leitura configurado."
)
