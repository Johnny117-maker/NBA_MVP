"""Gera o executável Windows portátil e o ZIP completo para distribuição."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from PIL import Image, ImageDraw

    from src.desktop_seed import build_seed
    from src.desktop_support import APP_VERSION

    parser = argparse.ArgumentParser(
        description="Gera a versão Windows sem instalação de Python pelo usuário."
    )
    parser.add_argument("--no-seed", action="store_true", help="Compila sem a base pública inicial.")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("O executável Windows deve ser compilado em Windows de 64 bits.")
    if sys.maxsize <= 2**32:
        raise SystemExit("Use Python de 64 bits para gerar esta versão.")
    build = ROOT / "build" / "desktop" / uuid.uuid4().hex
    seed = build / "seed"
    seed.mkdir(parents=True)
    icon = build / "icon.ico"
    image = Image.new("RGBA", (256, 256), "#0b1120")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 20, 236, 236), radius=40, fill="#f97316")
    draw.polygon(
        [
            (66, 190),
            (66, 66),
            (96, 66),
            (160, 145),
            (160, 66),
            (190, 66),
            (190, 190),
            (160, 190),
            (96, 111),
            (96, 190),
        ],
        fill="#0b1120",
    )
    image.save(icon, format="ICO", sizes=[(32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    initial = {}
    source = ROOT / "data" / "nba.db"
    if source.exists() and not args.no_seed:
        print("Preparando base pública histórica desde 2022...", flush=True)
        initial = build_seed(source, seed / "nba.db")
        print(json.dumps(initial, indent=2), flush=True)
        schedule = ROOT / "data" / "nba_schedule.json"
        if schedule.exists():
            shutil.copyfile(schedule, seed / schedule.name)
    environment = dict(os.environ, NBA_BUILD_SEED=str(seed), NBA_BUILD_ICON=str(icon))
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    environment["PATH"] = os.pathsep.join(
        str(p)
        for p in (
            Path(sys.executable).parent,
            Path(sys.base_prefix),
            Path(sys.base_prefix) / "DLLs",
            windows / "System32",
            windows,
        )
    )
    distribution = ROOT / "dist" / APP_VERSION
    target = (distribution / "NBAAnalyticsLab").resolve()
    if not target.is_relative_to((ROOT / "dist").resolve()):
        raise RuntimeError("Diretório de saída fora da pasta dist do projeto.")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(distribution),
            "--workpath",
            str(build / "pyinstaller"),
            str(ROOT / "desktop" / "NBAAnalyticsLab.spec"),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    package_distribution(target, initial)


def package_distribution(target: Path, initial: dict) -> None:
    """Atualiza os arquivos de distribuição e compacta um executável já compilado."""
    from src.desktop_support import APP_VERSION

    if not (target / "NBAAnalyticsLab.exe").is_file():
        raise FileNotFoundError("Compile o executável antes de montar o pacote.")
    # Também remove relatórios de compilações anteriores antes de reempacotar.
    reports = (target / "_internal" / "reports").resolve()
    if not reports.is_relative_to((ROOT / "dist").resolve()):
        raise ValueError("O pacote deve permanecer na pasta dist do projeto.")
    if reports.is_dir():
        shutil.rmtree(reports)
    shutil.copyfile(ROOT / "CRIAR_ATALHO.bat", target / "CRIAR_ATALHO.bat")
    for relative in ("README.md", "docs/EXECUTAVEL_WINDOWS.md"):
        shutil.copyfile(ROOT / relative, target / "_internal" / relative)
    readme = (
        "NBA ANALYTICS LAB - WINDOWS 64 BITS\n\n"
        "1. Extraia o ZIP inteiro para uma pasta.\n"
        "2. Abra NBAAnalyticsLab.exe.\n"
        "3. Mantenha a pasta _internal junto do executável.\n"
        "4. Opcional: execute CRIAR_ATALHO.bat para criar o icone na Area de Trabalho.\n\n"
        "Python, navegador e bibliotecas acompanham o pacote. Não há instalação de dependências.\n"
        "O sistema processa tudo localmente; a internet é necessária para novos dados da NBA.\n"
        "Seus dados ficam em %LOCALAPPDATA%\\NBAAnalyticsLab, separados da pasta do programa.\n"
        "Ao atualizar, substitua a pasta do programa; os dados pessoais serão preservados.\n"
        "Fechar a janela encerra a coleta. Minimizar mantém o sistema funcionando.\n\n"
        "Os palpites diários continuam sendo gerados no GitHub com o computador desligado.\n"
        "Consulte Histórico diário para sincronizar os registros remotos com sua conta GitHub.\n\n"
        "Menu Sistema: pasta dos dados, logs, recarregar e sair.\n"
        "Licenças das bibliotecas: diretórios .dist-info dentro de _internal.\n"
    )
    (target / "LEIA-ME.txt").write_text(readme, encoding="utf-8-sig")
    manifest = {
        "version": APP_VERSION,
        "platform": "Windows x64",
        "seed": initial,
        "external_python_required": False,
        "external_server_required": False,
        "mode": "portable-directory",
    }
    (target / "package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Compactando o pacote para distribuição...", flush=True)
    archive = Path(
        shutil.make_archive(
            str(ROOT / "dist" / f"NBAAnalyticsLab-{APP_VERSION}-Windows-x64"),
            "zip",
            root_dir=target.parent,
            base_dir=target.name,
        )
    )
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(
        json.dumps(
            {
                "executable": str(target / "NBAAnalyticsLab.exe"),
                "zip": str(archive),
                "zip_bytes": archive.stat().st_size,
                "sha256": digest,
            },
            indent=2,
        ),
        flush=True,
    )
    (ROOT / "dist" / "latest_build.json").write_text(
        json.dumps(
            {
                "version": APP_VERSION,
                "executable": str(target / "NBAAnalyticsLab.exe"),
                "zip": str(archive),
                "sha256": digest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
