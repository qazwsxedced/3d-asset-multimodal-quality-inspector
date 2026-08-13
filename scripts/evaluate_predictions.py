"""Evaluate structured asset-quality diagnosis predictions."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import DEFECT_TYPES, SEVERITIES, read_jsonl


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def multilabel_macro_f1(gold_sets: list[set[str]], pred_sets: list[set[str]]) -> float:
    scores = []
    for label in sorted(DEFECT_TYPES):
        tp = sum(label in g and label in p for g, p in zip(gold_sets, pred_sets))
        fp = sum(label not in g and label in p for g, p in zip(gold_sets, pred_sets))
        fn = sum(label in g and label not in p for g, p in zip(gold_sets, pred_sets))
        scores.append(f1(tp / (tp + fp) if tp + fp else 0.0, tp / (tp + fn) if tp + fn else 0.0))
    return sum(scores) / len(scores)


def valid_prediction(value: object) -> bool:
    if not isinstance(value, dict) or "_raw" in value:
        return False
    if value.get("quality") not in {"pass", "fail"}:
        return False
    if value.get("severity") not in SEVERITIES:
        return False
    defects = value.get("defect_types")
    return isinstance(defects, list) and set(defects).issubset(DEFECT_TYPES) and all(isinstance(x, str) for x in defects)


def syntactically_valid(value: object) -> bool:
    """Whether the decoder produced a JSON object, independent of schema."""
    return isinstance(value, dict) and "_raw" not in value


def normalized_defects(value: object) -> set[str]:
    if not isinstance(value, dict) or not isinstance(value.get("defect_types"), list):
        return set()
    return set(value["defect_types"]) & DEFECT_TYPES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    gold_rows = {r["id"]: r for r in read_jsonl(args.gold)}
    y_quality, p_quality = [], []
    y_severity, p_severity = [], []
    gold_defects, pred_defects = [], []
    json_valid = 0
    schema_valid = 0
    field_stats = defaultdict(lambda: [0, 0])
    by_group = defaultdict(lambda: {"n": 0, "quality_correct": 0, "gold_defects": [], "pred_defects": []})
    latencies = []
    repair_exact = []
    for item in read_jsonl(args.pred):
        row = gold_rows.get(item.get("id"))
        if not row:
            continue
        prediction = item.get("prediction")
        json_valid += int(syntactically_valid(prediction))
        schema_valid += int(valid_prediction(prediction))
        prediction = prediction if isinstance(prediction, dict) else {}
        gold = row["answer"]
        y_quality.append(gold.get("quality"))
        p_quality.append(prediction.get("quality"))
        y_severity.append(gold.get("severity"))
        p_severity.append(prediction.get("severity"))
        gd = set(gold.get("defect_types", []))
        raw_pred_defects = prediction.get("defect_types") if isinstance(prediction, dict) else None
        pd = normalized_defects(prediction)
        gold_defects.append(gd)
        pred_defects.append(pd)
        for field in ("quality", "severity"):
            field_stats[field][1] += 1
            field_stats[field][0] += int(prediction.get(field) == gold.get(field))
        field_stats["defect_types_exact"][1] += 1
        raw_set = set(raw_pred_defects) if isinstance(raw_pred_defects, list) and all(isinstance(x, str) for x in raw_pred_defects) else None
        field_stats["defect_types_exact"][0] += int(raw_set is not None and raw_set == gd and len(raw_pred_defects) == len(gd))
        if "repair_plan" in gold:
            field_stats["repair_plan_exact"][1] += 1
            field_stats["repair_plan_exact"][0] += int(prediction.get("repair_plan") == gold.get("repair_plan"))
            repair_exact.append(int(prediction.get("repair_plan") == gold.get("repair_plan")))
        group = row.get("generalization", "unknown")
        bucket = by_group[group]
        bucket["n"] += 1
        bucket["quality_correct"] += int(prediction.get("quality") == gold.get("quality"))
        bucket["gold_defects"].append(gd)
        bucket["pred_defects"].append(pd)
        if isinstance(item.get("latency_ms"), (int, float)):
            latencies.append(float(item["latency_ms"]))
    latencies.sort()
    percentile = lambda q: latencies[math.floor(q * (len(latencies) - 1))] if latencies else None
    group_metrics = {}
    for group, bucket in sorted(by_group.items()):
        group_metrics[group] = {
            "n": bucket["n"],
            "quality_accuracy": bucket["quality_correct"] / bucket["n"] if bucket["n"] else 0.0,
            "defect_macro_f1": multilabel_macro_f1(bucket["gold_defects"], bucket["pred_defects"]),
        }
    metrics = {
        "n": len(y_quality),
        "json_valid_rate": json_valid / len(y_quality) if y_quality else 0.0,
        "schema_valid_rate": schema_valid / len(y_quality) if y_quality else 0.0,
        "quality_accuracy": sum(a == b for a, b in zip(y_quality, p_quality)) / len(y_quality) if y_quality else 0.0,
        "severity_accuracy": sum(a == b for a, b in zip(y_severity, p_severity)) / len(y_severity) if y_severity else 0.0,
        "defect_macro_f1": multilabel_macro_f1(gold_defects, pred_defects),
        "field_accuracy": {k: v[0] / v[1] for k, v in sorted(field_stats.items())},
        "latency_ms": {"mean": sum(latencies) / len(latencies) if latencies else None, "p50": percentile(0.50), "p95": percentile(0.95)},
        "accuracy_by_generalization": group_metrics,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
