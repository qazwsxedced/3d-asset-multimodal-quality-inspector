"""Create an error-analysis report for structured asset-quality predictions."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import DEFECT_TYPES, read_jsonl


def safe_prediction(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def defect_set(value: object) -> set[str]:
    if not isinstance(value, dict) or not isinstance(value.get("defect_types"), list):
        return set()
    return {x for x in value["defect_types"] if isinstance(x, str) and x in DEFECT_TYPES}


def f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    gold = {row["id"]: row for row in read_jsonl(args.gold)}
    rows = []
    for item in read_jsonl(args.pred):
        row = gold.get(item.get("id"))
        if row is not None:
            rows.append((row, item, safe_prediction(item.get("prediction"))))

    defect_stats = {}
    for label in sorted(DEFECT_TYPES):
        tp = fp = fn = 0
        for row, _, pred in rows:
            g = set(row["answer"].get("defect_types", []))
            p = defect_set(pred)
            tp += int(label in g and label in p)
            fp += int(label not in g and label in p)
            fn += int(label in g and label not in p)
        defect_stats[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": f1(tp, fp, fn),
        }

    severity_confusion = Counter(
        (row["answer"].get("severity"), pred.get("severity"))
        for row, _, pred in rows
    )
    quality_confusion = Counter(
        (row["answer"].get("quality"), pred.get("quality"))
        for row, _, pred in rows
    )

    clean_gold = sum(not row["answer"].get("defect_types") for row, _, _ in rows)
    clean_pred = sum(not defect_set(pred) for _, _, pred in rows)
    clean_false_positive = sum(
        not row["answer"].get("defect_types") and bool(defect_set(pred))
        for row, _, pred in rows
    )
    clean_false_negative = sum(
        bool(row["answer"].get("defect_types")) and not defect_set(pred)
        for row, _, pred in rows
    )

    by_group = defaultdict(list)
    by_question = defaultdict(list)
    for row, item, pred in rows:
        record = {
            "id": row["id"],
            "generalization": row.get("generalization", "unknown"),
            "question_type": row.get("question_type", "unknown"),
            "gold": row["answer"],
            "prediction": pred,
            "latency_ms": item.get("latency_ms"),
        }
        by_group[record["generalization"]].append(record)
        by_question[record["question_type"]].append(record)

    def bucket_metrics(bucket: list[dict]) -> dict:
        quality_correct = sum(x["gold"].get("quality") == x["prediction"].get("quality") for x in bucket)
        exact = sum(
            set(x["gold"].get("defect_types", [])) == defect_set(x["prediction"])
            for x in bucket
        )
        return {
            "n": len(bucket),
            "quality_accuracy": quality_correct / len(bucket) if bucket else 0.0,
            "defect_exact_accuracy": exact / len(bucket) if bucket else 0.0,
            "clean_false_positive": sum(
                not x["gold"].get("defect_types") and bool(defect_set(x["prediction"]))
                for x in bucket
            ),
        }

    error_cases = []
    for row, item, pred in rows:
        gold_answer = row["answer"]
        gold_defects = set(gold_answer.get("defect_types", []))
        pred_defects = defect_set(pred)
        if (
            gold_answer.get("quality") != pred.get("quality")
            or gold_answer.get("severity") != pred.get("severity")
            or gold_defects != pred_defects
            or ("repair_plan" in gold_answer and pred.get("repair_plan") != gold_answer["repair_plan"])
        ):
            error_cases.append({
                "id": row["id"],
                "generalization": row.get("generalization"),
                "question_type": row.get("question_type"),
                "gold": gold_answer,
                "prediction": pred,
                "latency_ms": item.get("latency_ms"),
            })

    report = {
        "source": {"gold": str(args.gold), "pred": str(args.pred)},
        "n": len(rows),
        "clean_defect_balance": {
            "gold_clean": clean_gold,
            "gold_defect": len(rows) - clean_gold,
            "pred_clean": clean_pred,
            "clean_false_positive": clean_false_positive,
            "defect_false_negative_to_empty": clean_false_negative,
        },
        "quality_confusion": {f"{g}->{p}": n for (g, p), n in sorted(quality_confusion.items())},
        "severity_confusion": {f"{g}->{p}": n for (g, p), n in sorted(severity_confusion.items())},
        "per_defect": defect_stats,
        "by_generalization": {k: bucket_metrics(v) for k, v in sorted(by_group.items())},
        "by_question_type": {k: bucket_metrics(v) for k, v in sorted(by_question.items())},
        "error_case_count": len(error_cases),
        "error_cases": error_cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# Error Analysis",
        "",
        f"- Samples: {report['n']}",
        f"- Clean gold / defective gold: {clean_gold} / {len(rows) - clean_gold}",
        f"- Clean false positives: {clean_false_positive}",
        f"- Error cases: {len(error_cases)}",
        "",
        "## Per-defect metrics",
        "",
        "| Defect | Precision | Recall | F1 | TP | FP | FN |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, stats in defect_stats.items():
        md.append(f"| {label} | {stats['precision']:.3f} | {stats['recall']:.3f} | {stats['f1']:.3f} | {stats['tp']} | {stats['fp']} | {stats['fn']} |")
    md += ["", "## Generalization groups", "", "| Group | N | Quality accuracy | Defect exact accuracy | Clean false positives |", "|---|---:|---:|---:|---:|"]
    for group, stats in sorted(report["by_generalization"].items()):
        md.append(f"| {group} | {stats['n']} | {stats['quality_accuracy']:.3f} | {stats['defect_exact_accuracy']:.3f} | {stats['clean_false_positive']} |")
    md += ["", "## Question types", "", "| Question type | N | Quality accuracy | Defect exact accuracy | Clean false positives |", "|---|---:|---:|---:|---:|"]
    for question, stats in sorted(report["by_question_type"].items()):
        md.append(f"| {question} | {stats['n']} | {stats['quality_accuracy']:.3f} | {stats['defect_exact_accuracy']:.3f} | {stats['clean_false_positive']} |")
    args.out.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(args.out), "markdown": str(args.out.with_suffix('.md')), "error_case_count": len(error_cases)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
