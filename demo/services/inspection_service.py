"""Inspection orchestration independent from Gradio layout and callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.data_protocol import compact_metadata
from src.quality_scoring import compute_health_score


@dataclass(frozen=True)
class InspectionDependencies:
    """Functions supplied by the application layer during the migration."""

    run_rule: Callable[..., dict[str, Any]]
    get_vlm: Callable[..., dict[str, Any]]
    resolve_asset_profile: Callable[..., str]
    build_issue_details: Callable[..., list[dict[str, Any]]]
    build_complex_warnings: Callable[..., list[dict[str, Any]]]
    build_inspection_sections: Callable[..., list[dict[str, Any]]]
    build_asset_readiness: Callable[..., dict[str, Any]]
    build_confidence_report: Callable[..., dict[str, Any]]
    build_inspection_coverage: Callable[..., dict[str, Any]]
    build_inspection_coverage_details: Callable[..., dict[str, Any]]
    build_unified_issues: Callable[..., list[dict[str, Any]]]
    prioritize_issue_cards: Callable[..., list[dict[str, Any]]]
    resolve_image_paths: Callable[..., dict[str, Any]]


class InspectionService:
    """Build one result from rules, optional VLM output, and shared evidence."""

    def __init__(self, root: Path, dependencies: InspectionDependencies):
        self.root = root
        self.dependencies = dependencies

    def build_result(
        self,
        row: dict[str, Any],
        manifest: Path,
        mode: str,
        condition: str,
        model_id: str,
        adapter_text: str,
        max_new_tokens: int,
        min_pixels: int,
        max_pixels: int,
        offload_text: str,
        target_face_budget: str,
        reference_image: str | None = None,
        generation_prompt: str = "",
        thresholds: dict[str, Any] | None = None,
        asset_profile: str = "Auto",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        adapter = Path(adapter_text).expanduser() if adapter_text.strip() else None
        if adapter and not adapter.is_absolute():
            adapter = (self.root / adapter).resolve()
        offload_dir = Path(offload_text).expanduser()
        if not offload_dir.is_absolute():
            offload_dir = (self.root / offload_dir).resolve()

        thresholds = thresholds or {}
        reference_ready = bool(reference_image)
        prompt_ready = bool(generation_prompt.strip())
        rule_result = self.dependencies.run_rule(
            row,
            target_face_budget,
            reference_ready,
            prompt_ready,
            False,
            thresholds,
            asset_profile,
        )
        resolved_profile = rule_result["prediction"].get(
            "asset_profile",
            self.dependencies.resolve_asset_profile(asset_profile, row.get("metadata", {}), target_face_budget),
        )
        vlm_result = None
        if mode in {"VLM diagnosis", "Hybrid review"}:
            vlm_result = self.dependencies.get_vlm(
                row,
                manifest,
                condition,
                model_id,
                adapter,
                min_pixels,
                max_pixels,
                max_new_tokens,
                offload_dir,
                reference_image,
                generation_prompt,
            )
            rule_result["prediction"]["health_score"] = compute_health_score(
                row.get("metadata", {}),
                rule_result["prediction"].get("defect_types", []),
                target_face_budget,
                reference_ready,
                prompt_ready,
                True,
                int(thresholds.get("max_faces", 50_000)),
                asset_profile=resolved_profile,
            )

        rule_prediction = rule_result["prediction"]
        vlm_prediction = vlm_result["prediction"] if vlm_result else None
        metadata = row.get("metadata", {})
        if isinstance(vlm_prediction, dict) and "issue_details" not in vlm_prediction:
            vlm_prediction = dict(vlm_prediction)
            vlm_prediction["issue_details"] = self.dependencies.build_issue_details(
                metadata,
                vlm_prediction.get("defect_types", []) if isinstance(vlm_prediction.get("defect_types"), list) else [],
            )
        if isinstance(vlm_prediction, dict) and "warnings" not in vlm_prediction:
            vlm_prediction = dict(vlm_prediction)
            vlm_prediction["warnings"] = self.dependencies.build_complex_warnings(metadata, resolved_profile)
        if isinstance(vlm_prediction, dict) and "inspection_sections" not in vlm_prediction:
            vlm_prediction = dict(vlm_prediction)
            vlm_prediction["inspection_sections"] = self.dependencies.build_inspection_sections(
                metadata,
                vlm_prediction.get("defect_types", []) if isinstance(vlm_prediction.get("defect_types"), list) else [],
            )
        if isinstance(vlm_prediction, dict) and "asset_readiness" not in vlm_prediction:
            vlm_prediction = dict(vlm_prediction)
            vlm_prediction["asset_readiness"] = self.dependencies.build_asset_readiness(metadata)
        if isinstance(vlm_prediction, dict) and "confidence_report" not in vlm_prediction:
            vlm_prediction = dict(vlm_prediction)
            vlm_prediction["confidence_report"] = self.dependencies.build_confidence_report(
                metadata,
                vlm_prediction.get("defect_types", []) if isinstance(vlm_prediction.get("defect_types"), list) else [],
                target_face_budget,
                thresholds,
            )
        if isinstance(vlm_prediction, dict) and "health_score" not in vlm_prediction:
            vlm_prediction = dict(vlm_prediction)
            vlm_prediction["health_score"] = compute_health_score(
                metadata,
                vlm_prediction.get("defect_types", []) if isinstance(vlm_prediction.get("defect_types"), list) else [],
                target_face_budget,
                reference_ready,
                prompt_ready,
                bool(vlm_result),
                int(thresholds.get("max_faces", 50_000)),
                asset_profile=resolved_profile,
            )

        agreement = None
        review_required = False
        disagreement_reasons: list[str] = []
        if vlm_prediction is not None:
            rule_defects = set(rule_prediction.get("defect_types", []))
            vlm_defects = set(vlm_prediction.get("defect_types", [])) if isinstance(vlm_prediction.get("defect_types"), list) else set()
            agreement = round((len(rule_defects & vlm_defects) / len(rule_defects | vlm_defects)) if rule_defects | vlm_defects else 1.0, 3)
            if rule_defects != vlm_defects:
                disagreement_reasons.append("rule and VLM defect sets differ")
            if rule_prediction["quality"] != vlm_prediction.get("quality"):
                disagreement_reasons.append("rule and VLM quality decisions differ")
            if rule_prediction.get("severity") != vlm_prediction.get("severity"):
                disagreement_reasons.append("rule and VLM severity decisions differ")
            if not vlm_result["schema_valid"]:
                disagreement_reasons.append("VLM output failed schema validation")
            review_required = bool(disagreement_reasons)

        if mode == "Rule baseline":
            selected = rule_prediction
            selected_source = "rule_baseline"
        elif mode == "VLM diagnosis":
            selected = vlm_prediction or rule_prediction
            selected_source = "vlm"
        else:
            selected = dict(rule_prediction)
            if vlm_prediction:
                if vlm_prediction.get("repair_plan"):
                    selected["repair_plan"] = vlm_prediction["repair_plan"]
                selected["vlm_quality"] = vlm_prediction.get("quality")
                selected["vlm_defect_types"] = vlm_prediction.get("defect_types", [])
                selected["vlm_severity"] = vlm_prediction.get("severity")
            selected_source = "rule_gate_plus_vlm_explanation"

        selected = dict(selected)
        selected["asset_profile"] = resolved_profile
        selected["health_score"] = rule_prediction.get("health_score")
        selected["inspection_coverage"] = self.dependencies.build_inspection_coverage(metadata)
        selected["inspection_coverage_details"] = self.dependencies.build_inspection_coverage_details(metadata)
        selected["issues"] = self.dependencies.build_unified_issues(metadata, selected, target_face_budget, thresholds)
        selected["issues"] = self.dependencies.prioritize_issue_cards(selected["issues"], selected["health_score"])
        result = {
            "asset_id": row.get("scene_id", row.get("id")),
            "sample_id": row["id"],
            "mode": mode,
            "condition": condition,
            "question_type": row.get("question_type"),
            "selected_source": selected_source,
            "selected_result": selected,
            "rule_result": rule_result,
            "vlm_result": vlm_result,
            "agreement_score": agreement,
            "review_required": review_required,
            "disagreement_reasons": disagreement_reasons,
            "metadata": compact_metadata(metadata),
            "generalization": row.get("generalization"),
            "soft_inputs": {
                "reference_image_provided": reference_ready,
                "generation_prompt_provided": prompt_ready,
            },
        }
        return result, self.dependencies.resolve_image_paths(row, manifest)
