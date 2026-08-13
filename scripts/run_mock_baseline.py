"""Deterministic oracle-like baseline for testing the diagnosis evaluator."""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import build_condition, read_jsonl, write_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--condition", choices=["B0", "B1", "B2", "B3", "B4"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--noise", type=float, default=0.0, help="probability of corrupting one diagnosis field")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    predictions = []
    for row in read_jsonl(args.manifest):
        started = time.perf_counter()
        pred = dict(row["answer"])
        if rng.random() < args.noise:
            pred["quality"] = "pass" if pred["quality"] == "fail" else "fail"
        if rng.random() < args.noise / 2:
            pred["severity"] = rng.choice(["none", "low", "medium", "high"])
        payload = build_condition(row, args.condition, args.manifest)
        predictions.append({"id": row["id"], "condition": args.condition, "prediction": pred, "latency_ms": round((time.perf_counter() - started) * 1000, 3), "prompt": payload["prompt"]})
    write_jsonl(args.out, predictions)
    print(f"wrote {len(predictions)} predictions to {args.out}")


if __name__ == "__main__":
    main()
