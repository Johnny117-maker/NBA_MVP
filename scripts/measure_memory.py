"""Mede tamanho do pacote de dados e pico de memória ao abrir cada página.

Uso (na raiz do projeto, com ``requirements-dev.txt`` instalado)::

    python scripts/measure_memory.py                     # usa data/nba.db se houver dados reais
    python scripts/measure_memory.py --db caminho/nba.db # base real em outro lugar
    python scripts/measure_memory.py --synthetic         # força a base sintética pequena
    python scripts/measure_memory.py --json saida.json   # grava o resultado também em JSON

Cada página roda em um processo próprio (memória de pico isolada, via
``ru_maxrss``) com o banco **copiado** para um diretório temporário, então nada
do banco original é alterado. Quando não há banco real, usa-se uma base
sintética minúscula só para provar que o medidor funciona: **esses números não
representam o app em produção** e o relatório avisa isso. O limite do
Streamlit Community Cloud (cerca de 1 GB de RAM) só pode ser avaliado com a
base real.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAGE_TIMEOUT_SECONDS = 120


def pages() -> list[str]:
    """Home e todas as páginas, na ordem do menu."""
    found = sorted((ROOT / "pages").glob("*.py"), key=lambda p: int(p.name.split("_", 1)[0]))
    return ["app.py", *[f"pages/{p.name}" for p in found]]


def database_files(db_path: Path) -> list[Path]:
    """Banco principal e arquivos derivados que existirem ao lado dele."""
    names = [
        db_path.name,
        f"{db_path.stem}_sync.sqlite",
        f"{db_path.stem}_analysis.sqlite",
        "nba_history.sqlite",
    ]
    files = [db_path.with_name(name) for name in names if db_path.with_name(name).exists()]
    history = db_path.parent / "history"
    if history.is_dir():
        files += [p for p in history.rglob("*") if p.is_file()]
    return files


def total_bytes(files: list[Path]) -> int:
    return sum(path.stat().st_size for path in files)


def has_real_data(db_path: Path) -> bool:
    """Base real = existe e tem jogos coletados (a sintética dos testes não conta)."""
    if not db_path.exists():
        return False
    import sqlite3

    try:
        with sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            games = connection.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            players = connection.execute("SELECT COUNT(*) FROM player_game_stats").fetchone()[0]
    except sqlite3.Error:
        return False
    return int(games) >= 1000 and int(players) >= 10000


def build_synthetic_db(target: Path) -> None:
    """Gera a base pequena dos testes (mesmas funções de ``tests/conftest.py``)."""
    spec = importlib.util.spec_from_file_location("conftest_sintetico", ROOT / "tests" / "conftest.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("tests/conftest.py não encontrado para gerar a base sintética.")
    conftest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conftest)
    from src.player_data import generate_demo_player_games
    from src.shot_storage import upsert_player_shots
    from src.store import init_db, log_model_training, upsert_games, upsert_player_games

    init_db(target)
    upsert_games(conftest._synthetic_raw_games(), target)
    upsert_player_games(generate_demo_player_games(games_per_team=15), target)
    for player_id, name, team, seed in conftest.FIXTURE_SHOT_PLAYERS:
        upsert_player_shots(conftest._synthetic_shots_for_player(player_id, name, team, seed), target)
    log_model_training("team", 60, conftest._TEAM_METRICS, target)
    log_model_training("player", 500, conftest._PLAYER_METRICS, target)
    log_model_training("zone", 120, conftest._ZONE_METRICS, target)


def run_page_child(page: str) -> None:
    """Executa uma página no processo atual e imprime o pico de memória em JSON."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(ROOT / page), default_timeout=PAGE_TIMEOUT_SECONDS)
    app.run()
    peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":  # macOS informa bytes
        peak_kib //= 1024
    errors = [str(item.value) for item in app.exception]
    print(json.dumps({"page": page, "peak_mib": round(peak_kib / 1024, 1), "errors": errors}))


def measure_page(page: str, data_home: Path) -> dict:
    env = {**os.environ, "NBA_DATA_HOME": str(data_home), "NBA_AUTO_SYNC": "0"}
    try:
        done = subprocess.run(
            [sys.executable, __file__, "--child", page],
            env=env,
            capture_output=True,
            text=True,
            timeout=PAGE_TIMEOUT_SECONDS + 30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"page": page, "peak_mib": None, "errors": ["tempo esgotado"]}
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if done.returncode != 0 or not lines:
        return {"page": page, "peak_mib": None, "errors": [done.stderr.strip()[-300:] or "falha sem saída"]}
    return json.loads(lines[-1])


def format_report(origin: str, files: list[Path], size_bytes: int, results: list[dict]) -> str:
    size_mib = size_bytes / 1024 / 1024
    lines = [
        f"Origem dos dados: {origin}",
        f"Pacote de dados (soma dos arquivos copiados): {size_mib:.2f} MiB em {len(files)} arquivo(s)",
    ]
    if origin != "real":
        lines.append("AVISO: base sintética — tamanho e memória NÃO representam o app em produção.")
    lines += ["", f"{'Página':<34}{'Pico (MiB)':>12}  Erros"]
    for item in results:
        peak = "-" if item["peak_mib"] is None else f"{item['peak_mib']:.1f}"
        lines.append(f"{item['page']:<34}{peak:>12}  {'; '.join(item['errors'])[:60]}")
    peaks = [item["peak_mib"] for item in results if item["peak_mib"] is not None]
    if peaks:
        lines.append(f"\nMaior pico: {max(peaks):.1f} MiB")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--child", help="uso interno: executa uma página e mede o pico")
    parser.add_argument("--db", type=Path, help="caminho de um nba.db real")
    parser.add_argument("--synthetic", action="store_true", help="usa a base sintética pequena")
    parser.add_argument("--json", type=Path, help="grava o resultado em JSON")
    args = parser.parse_args(argv)
    if args.child:
        run_page_child(args.child)
        return 0

    candidate = args.db or ROOT / "data" / "nba.db"
    use_real = not args.synthetic and has_real_data(candidate)
    with tempfile.TemporaryDirectory(prefix="nba-medicao-") as temp:
        data_home = Path(temp)
        target = data_home / "data" / "nba.db"
        target.parent.mkdir(parents=True)
        if use_real:
            for source in database_files(candidate):
                relative = source.relative_to(candidate.parent)
                (target.parent / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target.parent / relative)
        else:
            build_synthetic_db(target)
        files = database_files(target)
        size_bytes = total_bytes(files)  # medido antes: as páginas podem criar arquivos auxiliares
        results = [measure_page(page, data_home) for page in pages()]
        origin = "real" if use_real else "sintética"
        print(format_report(origin, files, size_bytes, results))
    if args.json:
        payload = {"origin": origin, "bytes": size_bytes, "pages": results}
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(not item["errors"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
