from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.live_store import get_state
from src.remote_archive import BRANCH, ArchiveError, archive_repository, import_envelope, sync_remote_archive


def remote_archive_controls(path: str | Path, day: str | None = None) -> None:
    with st.expander("Arquivo automático do GitHub", expanded=False):
        st.caption(
            "O GitHub grava previsões e busca os resultados mesmo com este computador desligado. "
            "Previsões e resultados confirmados são sincronizados a cada 15 minutos com o sistema aberto."
        )
        status = get_state(path, "remote_archive_status", {})
        if status.get("checked_at"):
            stamp = pd.Timestamp(status["checked_at"]).tz_convert("America/Sao_Paulo")
            st.caption(f"Última sincronização local: {stamp:%d/%m/%Y %H:%M} · Brasília")
        if status.get("error"):
            st.info(status["error"])
        if st.button("Sincronizar previsões e resultados", key="sync_remote_picks"):
            try:
                with st.spinner("Importando o arquivo diário…"):
                    result = sync_remote_archive(path, day=day)
                st.success(
                    f"{result['imported']} previsões e {result.get('results_imported', 0)} resultados "
                    "novos importados. Originais locais preservados."
                )
            except ArchiveError as error:
                st.warning(str(error))
        repository = archive_repository()
        st.link_button(
            "Ver execução e eventuais falhas",
            f"https://github.com/{repository}/actions/workflows/daily-picks.yml",
        )
        st.link_button(
            "Abrir arquivo de previsões",
            f"https://github.com/{repository}/tree/{BRANCH}/archive",
        )
        st.caption(
            "Repositório privado: usa a autenticação GitHub local, NBA_GITHUB_ARCHIVE_TOKEN "
            "ou [archive].github_token na configuração protegida. O repositório vem de "
            "NBA_ARCHIVE_REPOSITORY ou [archive].repository (padrão: o repositório oficial). "
            "Em outro PC, use um token de Contents somente leitura ou importe os arquivos abaixo."
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
                result_documents = []
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
                    for item in documents:
                        if "records" in item.get("payload", {}):
                            result_documents.append(item)
                        else:
                            count += int(import_envelope(path, item))
                from src.result_archive import import_results

                results = sum(import_results(path, item) for item in result_documents)
                st.success(
                    f"{count} previsões e {results} resultados importados. Capturas originais preservadas."
                )
            except (ArchiveError, ValueError, KeyError, zipfile.BadZipFile):
                st.warning("Arquivo não importado por completo. Confira formato, tamanho e SHA-256.")
