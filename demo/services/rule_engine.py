"""Deterministic rule-inspection orchestration, independent of the UI."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.detector_registry import DEFAULT_DETECTOR_REGISTRY, DetectorContext
from src.quality_scoring import compute_health_score
from scripts.run_rule_baseline import infer_defects, infer_severity


@dataclass(frozen=True)
class RuleEngineDependencies:
    default_thresholds: Path
    load_thresholds: Callable[[Path], dict[str, Any]]
    resolve_asset_profile: Callable[[str, dict[str, Any], str], str]
    boundary_policy_for_profile: Callable[[str], str]
    build_issue_details: Callable[[dict[str, Any], list[str]], list[dict[str, Any]]]
    build_complex_warnings: Callable[[dict[str, Any], str], list[dict[str, Any]]]
    build_inspection_sections: Callable[[dict[str, Any], list[str]], list[dict[str, Any]]]
    build_asset_readiness: Callable[[dict[str, Any]], dict[str, Any]]
    build_confidence_report: Callable[..., dict[str, Any]]
    build_inspection_coverage: Callable[[dict[str, Any]], dict[str, str]]
    build_inspection_coverage_details: Callable[[dict[str, Any]], dict[str, dict[str, Any]]]
    build_unified_issues: Callable[..., list[dict[str, Any]]]
    prioritize_issue_cards: Callable[[list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]]


class RuleEngine:
    def __init__(self, dependencies: RuleEngineDependencies):
        self.dependencies = dependencies

    def evaluate(
        self,
        row: dict[str, Any],
        target_face_budget: str = "Auto",
        reference_image_provided: bool = False,
        prompt_provided: bool = False,
        soft_model_used: bool = False,
        thresholds: dict[str, Any] | None = None,
        asset_profile: str = "Auto",
    ) -> dict[str, Any]:
        metadata = row.get("metadata", {})
        thresholds = thresholds or self.dependencies.load_thresholds(self.dependencies.default_thresholds)
        resolved_profile = self.dependencies.resolve_asset_profile(asset_profile, metadata, target_face_budget)
        started = time.perf_counter()
        defects = infer_defects(
            metadata,
            uv_threshold=float(thresholds["max_uv_overlap_ratio"]),
            stretch_ratio=float(thresholds["max_triangle_aspect_p95"]),
            boundary_policy=self.dependencies.boundary_policy_for_profile(resolved_profile),
        )
        uv_analyzed = int(metadata.get("uv_analysis_analyzed_triangle_count", 0) or 0)
        uv_valid = int(metadata.get("uv_valid_triangle_count", 0) or 0)
        uv_invalid = bool(
            "uv_valid_triangle_count" in metadata
            and metadata.get("uv_status") == "present"
            and uv_analyzed > 0
            and uv_valid / uv_analyzed < 0.99
        )
        prediction: dict[str, Any] = {
            "quality": "pass" if not defects and not uv_invalid else "fail",
            "defect_types": defects,
            "severity": "high" if uv_invalid else infer_severity(defects),
            "asset_profile": resolved_profile,
        }
        detector_metadata = dict(metadata)
        detector_metadata["detected_defects"] = list(defects)
        prediction["detector_results"] = DEFAULT_DETECTOR_REGISTRY.run(
            DetectorContext(
                metadata=detector_metadata,
                thresholds=thresholds,
                asset_profile=resolved_profile,
                target_face_budget=target_face_budget,
            )
        )
        repair = {
            "non_manifold": "merge or separate non-manifold components",
            "uv_overlap": "repack overlapping UV islands",
            "flipped_normals": "recalculate and validate face normals",
            "hole": "fill boundary loops and inspect watertightness",
            "stretched_triangles": "rebuild stretched regions with better topology",
            "degenerate_faces": "remove zero-area faces and re-triangulate",
        }
        prediction["repair_plan"] = [repair[name] for name in defects]
        if uv_invalid:
            prediction["repair_plan"].append("re-unwrap UVs and confirm non-zero UV triangle areas")
        if not prediction["repair_plan"]:
            prediction["repair_plan"] = ["no repair required"]
        prediction["issue_details"] = self.dependencies.build_issue_details(metadata, defects)
        prediction["warnings"] = self.dependencies.build_complex_warnings(metadata, resolved_profile)
        prediction["inspection_sections"] = self.dependencies.build_inspection_sections(metadata, defects)
        prediction["asset_readiness"] = self.dependencies.build_asset_readiness(metadata)
        prediction["confidence_report"] = self.dependencies.build_confidence_report(metadata, defects, target_face_budget, thresholds)
        prediction["inspection_coverage"] = self.dependencies.build_inspection_coverage(metadata)
        prediction["inspection_coverage_details"] = self.dependencies.build_inspection_coverage_details(metadata)
        prediction["issues"] = self.dependencies.build_unified_issues(metadata, prediction, target_face_budget, thresholds)
        prediction["health_score"] = compute_health_score(
            metadata,
            defects,
            target_face_budget,
            reference_image_provided,
            prompt_provided,
            soft_model_used,
            int(thresholds["max_faces"]),
            asset_profile=resolved_profile,
        )
        prediction["issues"] = self.dependencies.prioritize_issue_cards(prediction["issues"], prediction["health_score"])
        return {
            "prediction": prediction,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "model": "deterministic_rule_baseline",
            "schema_valid": True,
        }
