"""Um monitor por processo, compartilhado pelas páginas e independente do navegador."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import streamlit as st

from .live_providers import ApiKeys
from .provider_settings import load_api_keys
from .season_sync import SeasonSync

_lock = threading.Lock()
_service: SeasonSync | None = None


@st.cache_resource(show_spinner=False, max_entries=1)
def get_sync_service(db_path: str) -> SeasonSync:
    global _service
    with _lock:
        # O singleton também evita threads órfãs quando o usuário limpa o cache do Streamlit.
        if _service is not None and _service.db_path != Path(db_path).resolve():
            _service.stop()
            _service = None
        if _service is None:
            try:
                providers = dict(st.secrets.get("providers", {}))
                keys = load_api_keys(providers)
            except (FileNotFoundError, KeyError, ValueError):
                keys = ApiKeys()
            _service = SeasonSync(db_path, keys).start()
        return _service


def ensure_auto_sync(db_path: str | Path) -> SeasonSync | None:
    if os.environ.get("NBA_AUTO_SYNC", "1").strip().lower() in {"0", "false", "off"}:
        return None
    return get_sync_service(str(Path(db_path).resolve()))


@st.fragment(run_every=30)
def watch_history_version(db_path: str) -> None:
    path = Path(db_path)
    version = path.stat().st_mtime_ns if path.exists() else 0
    key = "_nba_history_version:" + str(path.resolve())
    previous = st.session_state.get(key)
    st.session_state[key] = version
    if previous is not None and previous != version:
        st.rerun()
