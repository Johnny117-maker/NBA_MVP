"""Janela desktop com navegador incluído e processo de análise local controlado."""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from .desktop_support import (
    APP_NAME,
    APP_VERSION,
    available_port,
    default_user_root,
    initialize_user_data,
    instance_hash,
    resource_root,
    server_command,
)

logger = logging.getLogger(__name__)


def _local_request(url: str, *, token: str | None = None) -> dict:
    # Não usa proxy corporativo para uma comunicação que deve permanecer local.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = urllib.request.Request(url, data=b"" if token else None, headers=headers)
    with opener.open(request, timeout=0.5) as response:
        return json.loads(response.read())


def stop_backend(process: subprocess.Popen | None, url: str, token: str) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        _local_request(url + "/desktop/shutdown", token=token)
    except (OSError, ValueError):
        pass
    try:
        process.wait(timeout=7)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def _diagnose(root: Path, resources: Path, output: Path) -> int:
    import importlib

    import numpy as np
    from scipy.stats import nbinom
    from streamlit.file_util import get_static_dir
    from xgboost import XGBRegressor

    from .store import count_games, count_player_games, init_db

    versions, package_paths = {}, {}
    for name in (
        "streamlit",
        "numpy",
        "pandas",
        "scipy",
        "sklearn",
        "plotly",
        "xgboost",
        "nba_api",
        "PySide6",
        "pyarrow",
    ):
        module = importlib.import_module(name)
        versions[name] = str(getattr(module, "__version__", "incluído"))
        package_paths[name] = str(getattr(module, "__file__", ""))
    for name in (
        "src.model",
        "src.player_model",
        "src.shot_model",
        "src.ui.live",
        "src.ui.archive",
        "src.research_feeds",
        "src.shot_quality",
        "src.team_defense",
        "src.player_matchups",
        "src.player_defense_fit",
        "src.defense_analytics",
        "src.defense_charts",
        "src.injuries",
        "src.remote_archive",
        "src.daily_automation",
        "src.prop_feedback",
        "src.desktop_updates",
        "src.ui.defenders",
        "PySide6.QtWebEngineWidgets",
    ):
        importlib.import_module(name)
    init_db(root / "data" / "nba.db")
    model = XGBRegressor(n_estimators=2, max_depth=2, n_jobs=1)
    model.fit(np.arange(10, dtype=float).reshape(-1, 1), np.arange(10, dtype=float))
    predicted = float(model.predict(np.array([[5.0]]))[0])
    result: dict = {
        "version": APP_VERSION,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "resources": str(resources),
        "data_root": str(root),
        "packages": versions,
        "package_paths": package_paths,
        "xgboost_prediction": predicted,
        "bayes_mean": float(nbinom(4, 0.5).mean()),
        "app_script": (resources / "app.py").exists(),
        "pages": len(list((resources / "pages").glob("*.py"))),
        "styles": (resources / "src" / "ui" / "styles.css").exists(),
        "frontend": (Path(get_static_dir()) / "index.html").exists(),
        "games": count_games(root / "data" / "nba.db"),
        "player_games": count_player_games(root / "data" / "nba.db"),
    }
    result["ok"] = bool(
        result["app_script"] and result["styles"] and result["frontend"] and result["pages"] >= 15
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def _run_window(root: Path, resources: Path) -> int:
    from PySide6.QtCore import QLockFile, QSettings, QStandardPaths, QTimer, QUrl
    from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QLabel,
        QMainWindow,
        QMessageBox,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )

    application = QApplication([sys.argv[0]])
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("NBAAnalyticsLab")
    application.setWindowIcon(QIcon(str(resources / "desktop" / "assets" / "icon.svg")))
    lock = QLockFile(str(root / "desktop.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "O sistema já está aberto para este usuário.")
        return 0

    class AppPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            if url.scheme() in {"about", "data", "blob"}:
                return True
            if url.host() == "127.0.0.1" and url.port() == window.port:
                return True
            if is_main_frame and url.scheme() in {"https", "http"}:
                QDesktopServices.openUrl(url)
            return not is_main_frame

    class Window(QMainWindow):
        port: int
        url: str

        def __init__(self):
            super().__init__()
            self.setWindowTitle(APP_NAME)
            self.resize(1360, 900)
            self.setMinimumSize(1000, 680)
            self.settings = QSettings(str(root / "desktop.ini"), QSettings.Format.IniFormat)
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
            self.stack = QStackedWidget(self)
            self.setCentralWidget(self.stack)
            loading = QWidget()
            loading.setStyleSheet("background:#0b1120;color:#f8fafc;font:18px 'Segoe UI';")
            layout = QVBoxLayout(loading)
            layout.addStretch()
            title = QLabel("NBA Analytics Lab")
            title.setStyleSheet("font-size:32px;font-weight:700;color:#f97316;")
            layout.addWidget(title)
            self.message = QLabel("Preparando o sistema no seu computador…")
            layout.addWidget(self.message)
            layout.addStretch()
            self.stack.addWidget(loading)
            self.profile = QWebEngineProfile("NBAAnalyticsLab", self)
            self.profile.setPersistentStoragePath(str(root / "browser" / "storage"))
            self.profile.setCachePath(str(root / "browser" / "cache"))
            self.profile.downloadRequested.connect(self.download)
            self.view = QWebEngineView(self.stack)
            self.view.setPage(AppPage(self.profile, self.view))
            self.stack.addWidget(self.view)
            menu = self.menuBar().addMenu("Sistema")
            for label, callback in (
                ("Recarregar tela", self.view.reload),
                ("Buscar atualização", lambda: self.view.setUrl(QUrl(self.url + "/Sistema"))),
                ("Abrir pasta dos dados", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))),
                ("Abrir logs", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(root / "logs")))),
                ("Sobre", self.about),
                ("Sair", self.close),
            ):
                action = QAction(label, self)
                action.triggered.connect(callback)
                menu.addAction(action)
            self.statusBar().showMessage("Inicializando…")
            self.port = available_port()
            self.url = f"http://127.0.0.1:{self.port}"
            self.token = secrets.token_urlsafe(32)
            env = dict(os.environ, NBA_DESKTOP_TOKEN=self.token)
            self.log = (root / "logs" / "server.log").open("a", encoding="utf-8")
            options: dict = {}
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            self.process = subprocess.Popen(
                server_command(self.port, root, os.getpid()),
                env=env,
                cwd=root,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                **options,
            )
            self.started = time.monotonic()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.check_ready)
            self.timer.start(400)

        def about(self):
            QMessageBox.information(
                self,
                APP_NAME,
                f"{APP_NAME} · versão {APP_VERSION}\n\n"
                "Processamento e armazenamento locais.\n"
                "A internet é usada para consultar novos dados.\n\n"
                "Os dados permanecem salvos ao fechar o programa.\n"
                "As bibliotecas e suas licenças acompanham o pacote.",
            )

        def download(self, item):
            folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            target, _ = QFileDialog.getSaveFileName(
                self, "Salvar arquivo", str(Path(folder) / item.downloadFileName())
            )
            if target:
                item.setDownloadDirectory(str(Path(target).parent))
                item.setDownloadFileName(Path(target).name)
                item.accept()
            else:
                item.cancel()

        def check_ready(self):
            if self.process.poll() is not None or time.monotonic() - self.started > 120:
                self.timer.stop()
                self.message.setText("Não foi possível iniciar. Consulte Sistema → Abrir logs.")
                self.statusBar().showMessage("Inicialização interrompida")
                return
            try:
                state = _local_request(self.url + "/desktop/health")
                if state.get("instance") != instance_hash(self.token):
                    return
            except (OSError, ValueError):
                return
            self.timer.stop()
            self.view.setUrl(QUrl(self.url))
            self.stack.setCurrentWidget(self.view)
            self.statusBar().showMessage("Sistema local · seus dados são salvos automaticamente")

        def closeEvent(self, event: QCloseEvent) -> None:
            self.timer.stop()
            self.settings.setValue("geometry", self.saveGeometry())
            self.statusBar().showMessage("Encerrando o sistema…")
            stop_backend(self.process, self.url, self.token)
            self.log.close()
            event.accept()

    window = Window()
    window.show()
    try:
        return application.exec()
    finally:
        stop_backend(window.process, window.url, window.token)
        lock.unlock()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--data-dir", type=Path, default=default_user_root())
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--no-sync", action="store_true", help="Desativa a coleta automática nesta execução.")
    parser.add_argument("--diagnostico", type=Path, help="Grava um diagnóstico do pacote em JSON.")
    args = parser.parse_args(argv)
    root = args.data_dir.expanduser().resolve()
    resources = resource_root()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    os.environ["NBA_DATA_HOME"] = str(root)
    os.environ["PYTHONUTF8"] = "1"
    if args.no_sync:
        os.environ["NBA_AUTO_SYNC"] = "0"
    if sys.stdout is None or sys.stderr is None:
        output = (root / "logs" / ("server.log" if args.serve else "desktop.log")).open("a", encoding="utf-8")
        sys.stdout = sys.stderr = output
    try:
        if args.serve:
            from .desktop_backend import serve

            initialize_user_data(root, resources)
            serve(args.port, root, resources, args.parent_pid)
            return 0
        if args.diagnostico:
            initialize_user_data(root, resources)
            return _diagnose(root, resources, args.diagnostico)
        return _run_window(root, resources)
    except Exception:
        # Último recurso da inicialização: nada pode escapar sem registro, nem sem aviso ao usuário.
        logger.exception("Falha ao iniciar o sistema")
        detail = traceback.format_exc()
        (root / "logs" / "error.log").write_text(detail, encoding="utf-8")
        if not args.serve and not args.diagnostico and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"Não foi possível iniciar o sistema.\nConsulte: {root / 'logs' / 'error.log'}",
                APP_NAME,
                0x10,
            )
        return 1
