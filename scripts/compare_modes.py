"""Compare Rule-only, VLM-only, and conservative Hybrid predictions.

The hybrid policy selects the VLM only when it is schema-valid and agrees with
the deterministic rule on quality, severity, and defect set.  Otherwise the
rule prediction is selected and the sample is marked for human review.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import read_jsonl, write_jsonl
from scripts.evaluate_predictions import valid_prediction


def semantic_equal(left: dict, right: dict) -> bool:
    return (
        left.get("quality") == right.get("quality")
        and left.get("severity") == right.get("severity")
        and set(left.get("defect_types", [])) == set(right.get("defect_types", []))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--rule", type=Path, required=True)
    parser.add_argument("--vlm", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rule = {row["id"]: row for row in read_jsonl(args.rule)}
    vlm = {row["id"]: row for row in read_jsonl(args.vlm)}
    hybrid = []
    agreement = 0
    review = 0
    for sample_id in sorted(set(rule) & set(vlm)):
        rule_item = rule[sample_id]
        vlm_item = vlm[sample_id]
        rule_prediction = rule_item.get("prediction", {})
        vlm_prediction = vlm_item.get("prediction", {})
        agree = valid_prediction(vlm_prediction) and semantic_equal(rule_prediction, vlm_prediction)
        if agree:
            agreement += 1
            selected = vlm_prediction
            source = "vlm_agreement"
        else:
            review += 1
            selected = rule_prediction
            source = "rule_gate_review"
        latency = float(rule_item.get("latency_ms", 0.0) or 0.0) + float(vlm_item.get("latency_ms", 0.0) or 0.0)
        hybrid.append({
            "id": sample_id, "condition": "HYBRID", "prediction": selected,
            "raw_output": json.dumps(selected, ensure_ascii=False), "latency_ms": round(latency, 2),
            "model": "rule_plus_vlm", "adapter": vlm_item.get("adapter"),
            "selected_source": source, "review_required": not agree,
        })

    hybrid_path = args.out_dir / "hybrid_predictions.jsonl"
    write_jsonl(hybrid_path, hybrid)
    evaluator = Path(__file__).resolve().parent / "evaluate_predictions.py"
    metrics_paths = {}
    for name, pred_path in (("rule_only", args.rule), ("vlm_only", args.vlm), ("hybrid", hybrid_path)):
        metric_path = args.out_dir / f"{name}_metrics.json"
        subprocess.run([sys.executable, str(evaluator), "--gold", str(args.gold), "--pred", str(pred_path), "--out", str(metric_path)], check=True)
        metrics_paths[name] = json.loads(metric_path.read_text(encoding="utf-8"))

    summary = {
        "n_compared": len(hybrid), "agreement_count": agreement, "review_required_count": review,
        "agreement_rate": agreement / len(hybrid) if hybrid else 0.0, "metrics": metrics_paths,
        "hybrid_predictions": str(hybrid_path),
    }
    (args.out_dir / "comparison_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"n_compared": len(hybrid), "agreement_rate": summary["agreement_rate"], "review_required_count": review, "metrics": {k: {m: v.get(m) for m in ("quality_accuracy", "defect_macro_f1", "schema_valid_rate")} for k, v in metrics_paths.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
