"""Testa o pacote congelado, inclusive HTML/JavaScript e desligamento do servidor."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from src.desktop_runtime import _local_request, stop_backend
    from src.desktop_support import available_port, instance_hash

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--profile", type=Path, required=True, help="Perfil isolado para este teste.")
    args = parser.parse_args()
    executable = args.executable.resolve()
    profile = args.profile.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    diagnostic = profile / "diagnostic.json"
    options: dict = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"}
    }
    if sys.platform == "win32":
        windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
        environment["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
    # Rodar fora da instalação detecta dependências acidentais da pasta atual.
    common = {"cwd": profile, **options}
    subprocess.run(
        [str(executable), "--data-dir", str(profile), "--diagnostico", str(diagnostic), "--no-sync"],
        check=True,
        timeout=120,
        env=environment,
        **common,
    )
    result = json.loads(diagnostic.read_text(encoding="utf-8"))
    if not result["frozen"] or not result["ok"]:
        raise RuntimeError("Diagnóstico incompleto: " + json.dumps(result))
    resources = Path(result["resources"]).resolve()
    for name, location in result["package_paths"].items():
        if not Path(location).resolve().is_relative_to(resources):
            raise RuntimeError(f"Biblioteca externa ao pacote: {name} ({location})")
    port = available_port()
    token = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{port}"
    with (profile / "smoke.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(executable), "--serve", "--port", str(port), "--data-dir", str(profile), "--no-sync"],
            env=dict(environment, NBA_DESKTOP_TOKEN=token),
            stdout=log,
            stderr=subprocess.STDOUT,
            **common,
        )
        try:
            started = time.monotonic()
            while time.monotonic() - started < 60:
                if process.poll() is not None:
                    raise RuntimeError("O servidor do executável encerrou antes de ficar pronto.")
                try:
                    if _local_request(url + "/desktop/health")["instance"] == instance_hash(token):
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                raise TimeoutError("Servidor do executável não ficou pronto em 60 segundos.")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=10) as response:
                html = response.read().decode("utf-8")
                result["html_status"] = response.status
            assets = re.findall(r'<script\b[^>]*src="([^"]+)"', html)
            if not assets:
                raise RuntimeError("Página inicial sem o JavaScript do aplicativo.")
            result["javascript_assets"] = []
            for asset in assets:
                with opener.open(urljoin(url, asset), timeout=10) as response:
                    if "javascript" not in response.headers.get("Content-Type", ""):
                        raise RuntimeError("JavaScript indisponível: " + asset)
                    result["javascript_assets"].append({"url": asset, "bytes": len(response.read())})
            result["server_start_seconds"] = round(time.monotonic() - started, 2)
            stop_backend(process, url, token)
            if process.returncode != 0:
                raise RuntimeError(f"Servidor não encerrou normalmente: {process.returncode}")
            result["shutdown_exit_code"] = process.returncode
        finally:
            stop_backend(process, url, token)
    report = profile / "validation.json"
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report)}, indent=2))


if __name__ == "__main__":
    main()
