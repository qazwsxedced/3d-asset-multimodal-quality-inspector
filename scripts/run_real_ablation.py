"""Run B0-B3 on the same test split and evaluate each result."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--adapter", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for condition in ("B0", "B1", "B2", "B3"):
        pred = args.out / f"qwen_{condition}.jsonl"
        metrics = args.out / f"qwen_{condition}_metrics.json"
        cmd = [sys.executable, str(root / "scripts" / "run_vlm_inference.py"), "--manifest", str(args.manifest), "--condition", condition, "--model", args.model, "--out", str(pred), "--split", "test"]
        if args.limit: cmd += ["--limit", str(args.limit)]
        if args.adapter: cmd += ["--adapter", str(args.adapter)]
        subprocess.run(cmd, check=True)
        subprocess.run([sys.executable, str(root / "scripts" / "evaluate_predictions.py"), "--gold", str(args.manifest), "--pred", str(pred), "--out", str(metrics)], check=True)
        summary[condition] = json.loads(metrics.read_text(encoding="utf-8"))
    (args.out / "ablation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {m: v.get(m) for m in ("quality_accuracy", "severity_accuracy", "defect_macro_f1", "json_valid_rate")} for k, v in summary.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
