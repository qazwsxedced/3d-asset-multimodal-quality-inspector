"""Run a deterministic geometry-statistics baseline without using gold labels."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_protocol import DEFECT_TYPES, read_jsonl, write_jsonl

DEFECT_ORDER = [
    "degenerate_faces",
    "flipped_normals",
    "hole",
    "non_manifold",
    "stretched_triangles",
    "uv_overlap",
]
REPAIR = {
    "non_manifold": "merge or separate non-manifold components",
    "uv_overlap": "repack overlapping UV islands",
    "flipped_normals": "recalculate and validate face normals",
    "hole": "fill boundary loops and inspect watertightness",
    "stretched_triangles": "rebuild stretched regions with better topology",
    "degenerate_faces": "remove zero-area faces and re-triangulate",
}


def fit_family_thresholds(rows: list[dict], fit_split: str) -> dict[str, float]:
    """Fit robust triangle-aspect thresholds from metadata only, without labels."""
    ratios: dict[str, list[float]] = {}
    for row in rows:
        if fit_split != "all" and row.get("split") != fit_split:
            continue
        metadata = row.get("metadata", {})
        family = metadata.get("asset_family")
        aspect_stats = metadata.get("triangle_aspect_stats", {})
        feature = float(aspect_stats.get("p95", 0.0) or 0.0)
        if family and feature > 0:
            ratios.setdefault(family, []).append(feature)
    thresholds = {}
    for family, values in ratios.items():
        center = statistics.median(values)
        mad = statistics.median(abs(value - center) for value in values)
        thresholds[family] = center + max(6.0 * 1.4826 * mad, center * 0.10, 0.5)
    return thresholds


def infer_defects(
    metadata: dict,
    uv_threshold: float,
    stretch_ratio: float,
    family_thresholds: dict[str, float] | None = None,
    boundary_policy: str = "strict",
) -> list[str]:
    """Infer defects using only low-level metadata and fixed thresholds."""
    defects = set()
    if metadata.get("non_manifold_edge_count", 0) > 0:
        defects.add("non_manifold")
    if metadata.get("boundary_edge_count", 0) > 0 and boundary_policy == "strict":
        defects.add("hole")
    if metadata.get("flipped_normal_count", 0) > 0:
        defects.add("flipped_normals")
    if metadata.get("degenerate_face_count", 0) > 0:
        defects.add("degenerate_faces")
    if metadata.get("uv_overlap_ratio", 0.0) > uv_threshold or metadata.get("uv_overlap_triangle_count", 0) > 0:
        defects.add("uv_overlap")

    aspect_stats = metadata.get("triangle_aspect_stats", {})
    feature = float(aspect_stats.get("p95", 0.0) or 0.0)
    family = metadata.get("asset_family")
    threshold = (family_thresholds or {}).get(family, stretch_ratio)
    if feature > 0 and feature > threshold:
        defects.add("stretched_triangles")

    unknown = defects.difference(DEFECT_TYPES)
    if unknown:
        raise ValueError(f"unknown inferred defects: {sorted(unknown)}")
    return [name for name in DEFECT_ORDER if name in defects]


def infer_severity(defects: list[str]) -> str:
    if not defects:
        return "none"
    return "high" if len(defects) > 1 or "hole" in defects else "medium"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", choices=["train", "val", "test", "all"], default="test")
    ap.add_argument("--uv-threshold", type=float, default=0.001)
    ap.add_argument("--stretch-ratio", type=float, default=4.0, help="fallback triangle-aspect threshold when no fit manifest is supplied")
    ap.add_argument("--fit-manifest", type=Path, default=None, help="fit per-family stretch thresholds from metadata only")
    ap.add_argument("--fit-split", choices=["train", "val", "test", "all"], default="train")
    args = ap.parse_args()

    rows = read_jsonl(args.manifest)
    family_thresholds = fit_family_thresholds(read_jsonl(args.fit_manifest), args.fit_split) if args.fit_manifest else {}
    if args.split != "all":
        rows = [row for row in rows if row.get("split") == args.split]

    predictions = []
    for row in rows:
        defects = infer_defects(row["metadata"], args.uv_threshold, args.stretch_ratio, family_thresholds)
        prediction = {
            "quality": "pass" if not defects else "fail",
            "defect_types": defects,
            "severity": infer_severity(defects),
        }
        if row.get("question_type") == "repair_planning":
            prediction["repair_plan"] = [REPAIR[name] for name in defects] if defects else ["no repair required"]
        predictions.append({
            "id": row["id"],
            "condition": "RULE",
            "prediction": prediction,
            "raw_output": "",
            "latency_ms": 0.0,
            "model": "rule_baseline",
            "adapter": None,
        })

    write_jsonl(args.out, predictions)
    print(f"wrote {len(predictions)} rule-baseline predictions to {args.out}")
    if family_thresholds:
        print("fitted_family_stretch_thresholds:", {key: round(value, 4) for key, value in sorted(family_thresholds.items())})


if __name__ == "__main__":
    main()
