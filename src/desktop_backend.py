"""Servidor interno do executável, acessível apenas pelo próprio computador."""

from __future__ import annotations

import hmac
import os
import threading
import tomllib
from pathlib import Path

from .desktop_support import instance_hash


def serve(port: int, root: Path, resources: Path, parent_pid: int = 0) -> None:
    # Configura antes de importar Streamlit e os módulos que resolvem caminhos.
    os.environ["NBA_DATA_HOME"] = str(root)
    os.environ.update(
        {
            "STREAMLIT_GLOBAL_DEVELOPMENT_MODE": "false",
            "STREAMLIT_SERVER_ADDRESS": "127.0.0.1",
            "STREAMLIT_SERVER_PORT": str(port),
            "STREAMLIT_SERVER_HEADLESS": "true",
            "STREAMLIT_SERVER_FILE_WATCHER_TYPE": "none",
            "STREAMLIT_SERVER_RUN_ON_SAVE": "false",
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "STREAMLIT_BROWSER_SERVER_ADDRESS": "127.0.0.1",
            "STREAMLIT_CLIENT_TOOLBAR_MODE": "minimal",
        }
    )
    os.chdir(root)
    import streamlit as st
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from streamlit.web import bootstrap

    from .live_store import _owner_alive
    from .store import init_db

    # O empacotador pode importar Streamlit antes deste módulo. Reaplica as
    # opções como o launcher oficial: no pacote congelado, o valor padrão de
    # developmentMode seria True e impediria o carregamento da interface.
    bootstrap.load_config_options(
        {
            "global.developmentMode": False,
            "server.address": "127.0.0.1",
            "server.port": port,
            "server.baseUrlPath": "",
            "server.headless": True,
            "server.fileWatcherType": "none",
            "server.runOnSave": False,
            "browser.gatherUsageStats": False,
            "browser.serverAddress": "127.0.0.1",
            "client.toolbarMode": "minimal",
            "logger.level": "warning",
        }
    )
    init_db(root / "data" / "nba.db")
    token = os.environ["NBA_DESKTOP_TOKEN"]
    options = root / ".streamlit" / "secrets.toml"
    secrets = tomllib.loads(options.read_text(encoding="utf-8")) if options.exists() else {}

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"application": "nba-analytics-lab", "instance": instance_hash(token)})

    async def shutdown(request: Request) -> JSONResponse:
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            return JSONResponse({"error": "unauthorized"}, status_code=403)
        server.should_exit = True
        return JSONResponse({"status": "stopping"})

    app = st.App(
        str(resources / "app.py"),
        secrets=secrets,
        routes=[
            Route("/desktop/health", health),
            Route("/desktop/shutdown", shutdown, methods=["POST"]),
        ],
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    )
    finished = threading.Event()

    def watch_parent() -> None:
        while not finished.wait(2):
            if parent_pid > 0 and not _owner_alive(str(parent_pid)):
                server.should_exit = True
                return

    threading.Thread(target=watch_parent, name="desktop-parent-watch", daemon=True).start()
    try:
        server.run()
    finally:
        finished.set()
