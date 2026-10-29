# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, copy_metadata, get_package_paths

root = Path(SPECPATH).parent
seed_dir = Path(os.environ["NBA_BUILD_SEED"])
icon_path = Path(os.environ["NBA_BUILD_ICON"])
datas, binaries, hiddenimports = collect_all("streamlit", include_py_files=False)
datas += collect_data_files("xgboost")
binaries += collect_dynamic_libs("xgboost")
# Usa o runtime C++ redistribuído pelo próprio Qt antes de qualquer biblioteca
# carregar uma versão antiga do Windows/Python com o mesmo nome.
qt_dir = Path(get_package_paths("PySide6")[1])
binaries += [(str(file), ".") for file in qt_dir.glob("*140*.dll")]
for package in ("streamlit", "xgboost", "nba_api", "PySide6", "PySide6_Addons", "PySide6_Essentials",
                "shiboken6", "scikit-learn", "numpy", "scipy", "pandas", "plotly", "certifi", "pyarrow"):
    datas += copy_metadata(package)
for folder in ("pages", "src", ".streamlit", "docs", "desktop/assets"):
    for file in (root / folder).rglob("*"):
        if not file.is_file() or "__pycache__" in file.parts:
            continue
        if file.name == "secrets.toml" or file.suffix in {".pyc", ".csv"}:
            continue
        datas.append((str(file), str(file.parent.relative_to(root))))
datas += [(str(root / "app.py"), "."), (str(root / "README.md"), ".")]
for file in seed_dir.rglob("*"):
    if file.is_file():
        datas.append((str(file), str(Path("seed") / file.parent.relative_to(seed_dir))))
hiddenimports += [
    ".".join(file.relative_to(root).with_suffix("").parts).removesuffix(".__init__")
    for file in (root / "src").rglob("*.py")
]
analysis = Analysis(
    [str(root / "desktop_launcher.py")], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "_pytest", "mypy", "ruff", "IPython", "notebook", "jupyterlab", "PyQt5", "PyQt6"],
    noarchive=False,
)
# Qt para Windows 10/11 usa a ICU nativa do Windows. Uma ICU de ferramentas
# externas (por exemplo Poppler no PATH da máquina de build) tem exports
# incompatíveis e não deve substituir o componente do sistema operacional.
analysis.binaries = [entry for entry in analysis.binaries if Path(entry[0]).name.lower() != "icuuc.dll"]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="NBAAnalyticsLab", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    disable_windowed_traceback=False, icon=str(icon_path),
)
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="NBAAnalyticsLab")
