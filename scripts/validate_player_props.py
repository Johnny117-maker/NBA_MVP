"""Produz relatório e casos verificáveis; nunca grava palpites retroativos no arquivo diário."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.prop_training import load_research_history
    from src.prop_validation import probability_grid, temporal_audit

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--before-day", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = load_research_history(args.db, args.before_day)
    if history.empty:
        raise SystemExit("Sem histórico elegível para validar.")
    report, rows = temporal_audit(history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cases = args.output.with_suffix(".csv")
    (probability_grid(rows) if not rows.empty else rows).to_csv(cases, index=False)
    report["cases_sha256"] = hashlib.sha256(cases.read_bytes()).hexdigest()
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(json.dumps({"report": str(args.output), "rows": len(rows), "status": report["status"]}))


if __name__ == "__main__":
    main()
