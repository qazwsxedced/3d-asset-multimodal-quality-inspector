"""Run all B0-B3 conditions through a baseline and aggregate metrics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--noise", type=float, default=0.15)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    py = sys.executable
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for condition in ("B0", "B1", "B2", "B3"):
        pred = args.out / f"mock_{condition}.jsonl"
        metrics = args.out / f"mock_{condition}_metrics.json"
        subprocess.run([py, str(root / "scripts" / "run_mock_baseline.py"), "--manifest", str(args.manifest), "--condition", condition, "--noise", str(args.noise), "--out", str(pred)], check=True)
        subprocess.run([py, str(root / "scripts" / "evaluate_predictions.py"), "--gold", str(args.manifest), "--pred", str(pred), "--out", str(metrics)], check=True)
        summary[condition] = json.loads(metrics.read_text(encoding="utf-8"))
    (args.out / "ablation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {m: v[m] for m in ("classification_accuracy", "macro_f1", "json_valid_rate")} for k, v in summary.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
