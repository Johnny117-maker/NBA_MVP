from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.live_store import get_state
from src.remote_archive import ArchiveError, import_envelope, sync_remote_archive


def remote_archive_controls(path: str | Path, day: str | None = None) -> None:
    with st.expander("Arquivo automático do GitHub", expanded=False):
        st.caption(
            "O GitHub grava previsões mesmo com este computador desligado. "
            "O histórico local é sincronizado a cada 15 minutos com o sistema aberto."
        )
        status = get_state(path, "remote_archive_status", {})
        if status.get("checked_at"):
            stamp = pd.Timestamp(status["checked_at"]).tz_convert("America/Sao_Paulo")
            st.caption(f"Última sincronização local: {stamp:%d/%m/%Y %H:%M} · Brasília")
        if status.get("error"):
            st.info(status["error"])
        if st.button("Sincronizar previsões salvas no GitHub", key="sync_remote_picks"):
            try:
                with st.spinner("Importando o arquivo diário…"):
                    result = sync_remote_archive(path, day=day)
                st.success(f"{result['imported']} registros novos importados. Originais locais preservados.")
            except ArchiveError as error:
                st.warning(str(error))
        st.link_button(
            "Ver execução e eventuais falhas",
            "https://github.com/Johnny117-maker/NBA_MVP/actions/workflows/daily-picks.yml",
        )
        st.link_button(
            "Abrir arquivo de previsões",
            "https://github.com/Johnny117-maker/NBA_MVP/tree/codex/daily-archive/archive",
        )
        st.caption(
            "Repositório privado: usa a autenticação GitHub local, NBA_GITHUB_ARCHIVE_TOKEN "
            "ou [archive].github_token na configuração protegida. Em outro PC, use um token "
            "de Contents somente leitura ou importe os arquivos abaixo."
        )
        files = st.file_uploader(
            "Importar JSON ou ZIP baixados do arquivo GitHub",
            type=["json", "zip"],
            accept_multiple_files=True,
            key="remote_archive_files",
        )
        if files and st.button("Importar arquivos selecionados", key="import_remote_archive_files"):
            try:
                count = 0
                for file in files:
                    if file.size > 50_000_000:
                        raise ArchiveError("Arquivo maior que 50 MB.")
                    if file.name.lower().endswith(".zip"):
                        with zipfile.ZipFile(io.BytesIO(file.getvalue())) as archive:
                            entries = [
                                item
                                for item in archive.infolist()
                                if item.filename.endswith(".json")
                                and not item.filename.endswith(("manifest.json", "index.json"))
                            ]
                            if len(entries) > 2000 or sum(item.file_size for item in entries) > 100_000_000:
                                raise ArchiveError("ZIP excede o limite de importação.")
                            documents = [json.loads(archive.read(item)) for item in entries]
                    else:
                        documents = [json.loads(file.getvalue())]
                    count += sum(int(import_envelope(path, item)) for item in documents)
                st.success(f"{count} registros importados. Nenhuma previsão local foi substituída.")
            except (ArchiveError, ValueError, KeyError, zipfile.BadZipFile):
                st.warning("Arquivo não importado por completo. Confira formato, tamanho e SHA-256.")
