"""Deterministic hard-metric health scoring for generated 3D assets."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from pathlib import Path

from src.inspection_enums import CheckStatus, CoverageStatus
from src.coverage_policy import has_material_statistics, has_runtime_statistics


FACE_BUDGETS = {
    "Auto": None,
    "50k": 50_000,
    "1m": 1_000_000,
    "1.5m": 1_500_000,
}

DEFECT_PENALTIES = {
    "non_manifold": 22,
    "hole": 20,
    "degenerate_faces": 15,
    "uv_overlap": 12,
    "flipped_normals": 10,
    "stretched_triangles": 8,
}

# The health score remains a hard-metric release gate.  These weights are a
# separate, explicit policy score that answers a different question: "How
# well does this measured asset fit the selected delivery profile?" Keeping
# the two scores separate prevents a realtime asset from looking healthy just
# because it is small, or a print asset from looking healthy just because it
# has good textures.
PROFILE_COMPONENT_WEIGHTS = {
    "static_geometry": {"geometry_and_defects": 0.60, "uv": 0.075, "materials": 0.075, "runtime": 0.25},
    "realtime_or_xr": {"geometry_and_defects": 0.30, "uv": 0.125, "materials": 0.125, "runtime": 0.45},
    "visual_display": {"geometry_and_defects": 0.25, "uv": 0.25, "materials": 0.30, "runtime": 0.20},
    "3d_printing": {"geometry_and_defects": 0.75, "uv": 0.025, "materials": 0.025, "runtime": 0.20},
    "character_or_animated": {
        "geometry_and_defects": 0.15,
        "uv": 0.075,
        "materials": 0.075,
        "runtime": 0.10,
        "skinning": 0.30,
        "animation": 0.30,
    },
    "textured_asset": {"geometry_and_defects": 0.25, "uv": 0.25, "materials": 0.25, "runtime": 0.25},
}

PROFILE_ALIASES = {
    "Realtime / XR": "realtime_or_xr",
    "Visual display / open surface": "visual_display",
    "3D printing / watertight": "3d_printing",
    "Character / animation": "character_or_animated",
}

PROFILE_COMPONENT_LABELS = {
    "geometry_and_defects": ("几何", "Geometry"),
    "uv": ("UV", "UV"),
    "materials": ("材质", "Materials"),
    "runtime": ("运行时", "Runtime"),
    "skinning": ("蒙皮", "Skinning"),
    "animation": ("动画", "Animation"),
}

DEFAULT_SCORING_CONFIG = Path(__file__).resolve().parents[1] / "config" / "inspection_scoring.json"


def load_scoring_config(path: Path = DEFAULT_SCORING_CONFIG) -> dict[str, Any]:
    """Load score policy from JSON while retaining safe code defaults."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {
            "config_version": "builtin-fallback",
            "defect_penalties": dict(DEFECT_PENALTIES),
            "profiles": {key: {"weights": dict(value)} for key, value in PROFILE_COMPONENT_WEIGHTS.items()},
        }
    if not isinstance(config, dict):
        raise ValueError(f"Scoring config must be a JSON object: {path}")
    return config


def scoring_config_hash(config: dict[str, Any]) -> str:
    """Hash the effective score policy for reproducible reports."""
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_health_score(
    metadata: dict[str, Any],
    defects: list[str],
    target_face_budget: str = "Auto",
    reference_image_provided: bool = False,
    prompt_provided: bool = False,
    soft_model_used: bool = False,
    configured_face_budget: int | None = None,
    asset_profile: str | None = None,
    scoring_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score observable quality signals; do not imply subjective visual quality."""
    policy = scoring_config or load_scoring_config()
    configured_penalties = policy.get("defect_penalties", {}) or {}
    effective_defect_penalties = {**DEFECT_PENALTIES, **{str(key): int(value) for key, value in configured_penalties.items()}}
    textured = int(metadata.get("texture_image_count", 0) or 0) > 0
    rigged = bool(metadata.get("source_has_armature") or metadata.get("source_has_animation"))
    realtime_target = target_face_budget != "Auto" or bool(metadata.get("source_lod_count"))
    requested_profile = str(asset_profile or "").strip()
    explicit_profile = PROFILE_ALIASES.get(requested_profile, requested_profile)
    if explicit_profile in PROFILE_COMPONENT_WEIGHTS:
        profile = explicit_profile
    elif rigged:
        profile = "character_or_animated"
    elif realtime_target:
        profile = "realtime_or_xr"
    elif textured:
        profile = "textured_asset"
    else:
        profile = "static_geometry"
    profile_focus_by_name = {
        "static_geometry": ["topology", "normals", "geometry"],
        "realtime_or_xr": ["triangle_budget", "runtime", "material", "UV"],
        "visual_display": ["material", "UV", "geometry", "runtime"],
        "3d_printing": ["watertightness", "topology", "geometry", "normals"],
        "character_or_animated": ["skinning", "animation", "UV", "material", "runtime"],
        "textured_asset": ["UV", "material", "texture_memory", "geometry"],
    }
    profile_focus = profile_focus_by_name[profile]
    budget = FACE_BUDGETS.get(target_face_budget)
    budget_label = target_face_budget
    if budget is None and target_face_budget == "Auto" and configured_face_budget:
        budget = int(configured_face_budget)
        budget_label = f"configured:{budget}"
    face_count = int(metadata.get("triangle_count", metadata.get("face_count", 0)) or 0)
    penalties: list[dict[str, Any]] = []

    for defect in defects:
        penalty = effective_defect_penalties.get(defect, 0)
        if penalty:
            penalties.append({"code": defect, "penalty": penalty, "reason": "detected blocking geometry/UV defect"})

    if metadata.get("loose_vertex_count", 0) > 0:
        penalties.append({"code": "loose_vertices", "penalty": 5, "reason": "unconnected vertices"})
    if metadata.get("zero_length_edge_count", 0) > 0 and "degenerate_faces" not in defects:
        penalties.append({"code": "zero_length_edges", "penalty": 8, "reason": "near-zero-length edges"})
    if metadata.get("uv_out_of_bounds_loop_count", 0) > 0 and "uv_overlap" not in defects:
        penalties.append({"code": "uv_out_of_bounds", "penalty": 5, "reason": "UV coordinates outside 0-1"})
    uv_analyzed = int(metadata.get("uv_analysis_analyzed_triangle_count", 0) or 0)
    uv_valid = int(metadata.get("uv_valid_triangle_count", 0) or 0)
    if "uv_valid_triangle_count" in metadata and metadata.get("uv_status") == "present" and uv_analyzed > 0 and uv_valid / uv_analyzed < 0.99:
        penalties.append({
            "code": "uv_invalid",
            "penalty": 18,
            "reason": f"only {uv_valid}/{uv_analyzed} analyzed UV triangles have usable area",
        })
    if metadata.get("missing_texture_count", 0) > 0:
        penalties.append({"code": "missing_textures", "penalty": 10, "reason": "referenced texture files are missing"})
    if metadata.get("low_resolution_texture_count", 0) > 0:
        penalties.append({"code": "low_resolution_textures", "penalty": 5, "reason": "one or more texture maps are below 512px"})
    if textured and metadata.get("source_missing_uv_object_count", 0) > 0:
        penalties.append({"code": "missing_source_uv", "penalty": 12 if profile in {"textured_asset", "realtime_or_xr"} else 8, "reason": "textured source mesh objects do not provide UVs"})
    if metadata.get("pbr_channel_issue_count", 0) > 0:
        penalties.append({"code": "pbr_channel_issues", "penalty": min(20, int(metadata.get("pbr_channel_issue_count", 0)) * 2), "reason": "PBR channel wiring or color-space issues"})
    if metadata.get("loading_risk") == "high":
        penalties.append({"code": "high_loading_risk", "penalty": 10 if profile == "realtime_or_xr" else 6, "reason": "estimated runtime loading risk is high"})
    elif metadata.get("loading_risk") == "medium":
        penalties.append({"code": "medium_loading_risk", "penalty": 4, "reason": "estimated runtime loading risk is medium"})
    if rigged:
        unbound_ratio = float(metadata.get("unbound_vertex_ratio", 0.0) or 0.0)
        weight_ratio = float(metadata.get("weight_sum_error_ratio", 0.0) or 0.0)
        if unbound_ratio > 0:
            penalties.append({"code": "unbound_vertex_ratio", "penalty": min(12, max(2, round(unbound_ratio * 100))), "reason": "some rigged vertices have no weights"})
        if weight_ratio > 0:
            penalties.append({"code": "weight_sum_error_ratio", "penalty": min(10, max(2, round(weight_ratio * 100))), "reason": "some vertex weight sums are outside tolerance"})

    budget_overrun = 0.0
    if budget and face_count > budget:
        budget_overrun = round((face_count - budget) / budget, 3)
        penalties.append({
            "code": "face_budget_exceeded",
            "penalty": min(25, 10 + round(budget_overrun * 20)),
            "reason": f"{face_count} triangles exceed the {budget_label} target",
        })

    total_penalty = min(100, sum(item["penalty"] for item in penalties))
    score = max(0, 100 - total_penalty)
    blocking_codes = {"non_manifold", "hole", "degenerate_faces", "uv_overlap", "uv_invalid", "face_budget_exceeded", "missing_textures"}
    if textured and metadata.get("source_missing_uv_object_count", 0) > 0:
        blocking_codes.add("missing_source_uv")
    blocking = [item for item in penalties if item["code"] in blocking_codes]
    # Keep the release gate separate from the numeric score. A blocking
    # problem still prevents release, but a small non-blocking warning should
    # not be inflated into an arbitrary 79-point ceiling.
    if blocking:
        score = min(score, 59)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    if blocking:
        disposition = "block_and_retry"
    elif penalties:
        disposition = "review_before_release"
    else:
        disposition = "pass_hard_checks"
    release_decision = {
        "status": "blocked" if blocking else "manual_review" if penalties else "pass",
        "reason_codes": [item["code"] for item in blocking] if blocking else [item["code"] for item in penalties],
        "score_is_independent": True,
    }

    hard_checks = [
        {"name": "topology_and_watertightness", "status": CheckStatus.FAILED.value if any(item in defects for item in ("hole", "non_manifold", "degenerate_faces")) else CheckStatus.PASSED.value, "evidence": {key: metadata.get(key, 0) for key in ("boundary_edge_count", "non_manifold_edge_count", "degenerate_face_count", "loose_vertex_count")}},
        {"name": "face_budget", "status": CheckStatus.FAILED.value if budget_overrun else CheckStatus.PASSED.value if budget else CheckStatus.NOT_CHECKED.value, "target": budget_label, "face_count": face_count, "overrun_ratio": budget_overrun},
        {"name": "normals", "status": CheckStatus.FAILED.value if "flipped_normals" in defects else CheckStatus.PASSED.value, "flipped_normal_count": metadata.get("flipped_normal_count", 0)},
        {"name": "uv_and_texture", "status": CheckStatus.FAILED.value if "uv_overlap" in defects or metadata.get("missing_texture_count", 0) else CheckStatus.PASSED.value, "evidence": {key: metadata.get(key, 0) for key in ("uv_overlap_ratio", "uv_overlap_triangle_count", "missing_texture_count")}},
        {"name": "pbr_material_wiring", "status": CheckStatus.FAILED.value if metadata.get("pbr_channel_issue_count", 0) else CheckStatus.PASSED.value, "issue_count": metadata.get("pbr_channel_issue_count", 0), "material_count": metadata.get("material_count", 0)},
        {"name": "runtime_readiness", "status": metadata.get("loading_risk", "not_available"), "estimated_draw_calls": metadata.get("estimated_draw_calls", 0), "estimated_load_time_seconds": metadata.get("estimated_load_time_seconds", 0)},
    ]
    if rigged:
        hard_checks.append({
            "name": "skinning_weights",
            "status": CheckStatus.FAILED.value if metadata.get("unbound_vertex_count", 0) or metadata.get("weight_sum_error_count", 0) else CheckStatus.PASSED.value,
            "unbound_vertex_ratio": metadata.get("unbound_vertex_ratio", 0),
            "weight_sum_error_ratio": metadata.get("weight_sum_error_ratio", 0),
        })
    if soft_model_used:
        soft_evaluation = {
            "status": "vlm_assisted",
            "reference_image_provided": reference_image_provided,
            "prompt_provided": prompt_provided,
            "reason_zh": "已将参考图/提示词作为 VLM 诊断上下文；当前健康度数值仍只由硬指标计算。",
            "reason_en": "The reference image/prompt was passed to VLM diagnosis; the numeric health score still uses hard metrics only.",
            "next_step_zh": "结合 VLM 的一致性、视角稳定性和美学描述进行人工复核；需要时再接入独立 CLIP/VLM 打分器。",
            "next_step_en": "Review VLM comments on consistency, view stability, and aesthetics; add a calibrated CLIP/VLM scorer when needed.",
        }
    elif reference_image_provided or prompt_provided:
        soft_evaluation = {
            "status": "inputs_ready",
            "reference_image_provided": reference_image_provided,
            "prompt_provided": prompt_provided,
            "reason_zh": "已收集参考图/提示词，但当前规则模式未调用视觉模型，因此尚未生成软评估分数。",
            "reason_en": "Reference image/prompt inputs are ready, but rule mode did not call a vision model, so no soft score was produced.",
            "next_step_zh": "切换到 VLM diagnosis 或 Hybrid review，检查生成内容与参考输入的一致性。",
            "next_step_en": "Switch to VLM diagnosis or Hybrid review to assess consistency against the reference inputs.",
        }
    else:
        soft_evaluation = {
            "status": "not_available",
            "reason_zh": "本次检测没有提供参考图、文本提示或视觉质量模型。",
            "reason_en": "No reference image, text prompt, or visual-quality model was provided in this run.",
            "next_step_zh": "提供参考图或文本提示后，再运行 CLIP/VLM 一致性和美学评估。",
            "next_step_en": "Provide a reference image or prompt and run a CLIP/VLM consistency and aesthetics evaluator.",
        }
    component_codes = {
        "geometry_and_defects": set(DEFECT_PENALTIES) - {"uv_overlap"} | {"loose_vertices", "zero_length_edges", "face_budget_exceeded"},
        "uv": {"uv_overlap", "missing_source_uv", "uv_invalid", "uv_out_of_bounds"},
        "materials": {"missing_textures", "low_resolution_textures", "pbr_channel_issues"},
        "runtime": {"high_loading_risk", "medium_loading_risk"},
        "skinning": {"unbound_vertex_ratio", "weight_sum_error_ratio"},
    }
    component_penalties = {
        component: [item for item in penalties if item["code"] in codes]
        for component, codes in component_codes.items()
    }
    geometry_component = max(0, 100 - sum(item["penalty"] for item in component_penalties["geometry_and_defects"]))
    uv_component = max(0, 100 - sum(item["penalty"] for item in component_penalties["uv"]))
    materials_component = max(0, 100 - sum(item["penalty"] for item in component_penalties["materials"]))
    score_components = {
        "geometry_and_defects": geometry_component,
        "uv": uv_component,
        "materials": materials_component,
        # Kept as a compatibility summary for older consumers. New profile
        # weights use the separate UV and materials components above.
        "material_and_uv": round((uv_component + materials_component) / 2, 1),
        "runtime": max(0, 100 - sum(item["penalty"] for item in component_penalties["runtime"])),
        "skinning": max(0, 100 - sum(item["penalty"] for item in component_penalties["skinning"])),
    }
    deformation_status = metadata.get("deformation_self_intersection_check")
    if not rigged or deformation_status == "not_applicable":
        score_components["animation"] = 100
    elif deformation_status == "detected_sampled_overlap":
        overlap_pairs = int(metadata.get("deformation_self_intersection_pair_count", 0) or 0)
        animation_penalty = min(40, 20 + overlap_pairs)
        score_components["animation"] = max(0, 100 - animation_penalty)
        component_penalties["animation"] = [{
            "code": "deformation_self_intersection",
            "penalty": animation_penalty,
            "reason": f"sampled deformation found {overlap_pairs} non-adjacent overlap pair(s)",
        }]
    elif deformation_status == "passed_sampled_no_non_adjacent_overlap":
        score_components["animation"] = 100
    else:
        # A missing deformation sample is not a failure, but it must not be
        # presented as a fully verified animation result.
        score_components["animation"] = 70
        component_penalties["animation"] = [{
            "code": "animation_probe_incomplete",
            "penalty": 30,
            "reason": "animation deformation was not fully sampled",
        }]
    component_penalties.setdefault("animation", [])
    uv_available = int(metadata.get("uv_layer_count", metadata.get("source_uv_layer_count", 0)) or 0) > 0 and metadata.get("uv_status", "present") != "not_present"
    uv_sampled = bool(metadata.get("uv_analysis_sampled") or metadata.get("uv_overlap_analysis_sampled"))
    material_stats_available = has_material_statistics(metadata)
    runtime_stats_available = has_runtime_statistics(metadata)
    geometry_stats_available = bool(metadata.get("vertex_count") and metadata.get("face_count"))
    deformation_sampled = bool(metadata.get("deformation_self_intersection_sample_count", 0))
    component_status = {
        "geometry_and_defects": CoverageStatus.CHECKED.value if geometry_stats_available else CoverageStatus.NOT_CHECKED.value,
        "uv": CoverageStatus.SAMPLED.value if uv_sampled else CoverageStatus.CHECKED.value if uv_available else CoverageStatus.NOT_CHECKED.value if metadata.get("texture_image_count", 0) else CoverageStatus.NOT_APPLICABLE.value,
        "materials": CoverageStatus.CHECKED.value if material_stats_available else CoverageStatus.NOT_CHECKED.value,
        "runtime": CoverageStatus.CHECKED.value if runtime_stats_available else CoverageStatus.NOT_CHECKED.value,
        "skinning": CoverageStatus.CHECKED.value if rigged else CoverageStatus.NOT_APPLICABLE.value,
        "animation": CoverageStatus.SAMPLED.value if deformation_sampled else CoverageStatus.NOT_CHECKED.value if rigged else CoverageStatus.NOT_APPLICABLE.value,
    }
    component_coverage = {
        "geometry_and_defects": 1.0 if geometry_stats_available else 0.0,
        # Sampling is intentionally capped below full coverage even when the
        # sampled counter happens to equal the current diagnostic subset.
        "uv": min(0.95, round(float(metadata.get("uv_analysis_coverage_ratio", 1.0) or 0.0), 4)) if uv_sampled else 1.0 if uv_available else 0.0,
        "materials": 1.0 if material_stats_available else 0.0,
        "runtime": 1.0 if runtime_stats_available else 0.0,
        "skinning": 1.0 if rigged else 0.0,
        # Pose/deformation probes inspect selected frames, not the complete
        # animation timeline, so they must lower confidence by design.
        "animation": 0.5 if deformation_sampled else 0.5 if rigged and metadata.get("animation_playability") not in {None, "not_available"} else 0.0,
    }
    configured_profile = (policy.get("profiles", {}) or {}).get(profile, {}) or {}
    raw_profile_weights = {
        **PROFILE_COMPONENT_WEIGHTS[profile],
        **{str(key): float(value) for key, value in (configured_profile.get("weights", {}) or {}).items()},
    }
    excluded_components = []
    applicable_profile_weights = {}
    for key, weight in raw_profile_weights.items():
        if component_status.get(key) in {"not_checked", "not_applicable"}:
            excluded_components.append(key)
            continue
        applicable_profile_weights[key] = weight
    weight_total = sum(applicable_profile_weights.values()) or 1.0
    profile_fit_score = round(sum(score_components[key] * weight for key, weight in applicable_profile_weights.items()) / weight_total, 1) if applicable_profile_weights else None
    profile_coverage = round(sum(component_coverage.get(key, 0.0) * weight for key, weight in applicable_profile_weights.items()) / weight_total, 4) if applicable_profile_weights else 0.0
    profile_confidence = "high" if profile_coverage >= 0.95 else "medium" if profile_coverage >= 0.70 else "low"
    profile_fit_contributions = [
        {
            "component": key,
            "label_zh": PROFILE_COMPONENT_LABELS.get(key, (key, key))[0],
            "label_en": PROFILE_COMPONENT_LABELS.get(key, (key, key))[1],
            "score": score_components[key],
            "weight": weight,
            "weighted_contribution": round(score_components[key] * weight / weight_total, 2),
            "status": component_status.get(key, "not_checked"),
            "coverage": component_coverage.get(key, 0.0),
            "quality_gap": round((100 - score_components[key]) * weight / weight_total, 2),
            "coverage_uncertainty": round((1 - component_coverage.get(key, 0.0)) * weight / weight_total * 100, 2),
            "priority_score": round(
                (100 - score_components[key]) * weight / weight_total
                + (1 - component_coverage.get(key, 0.0)) * weight / weight_total * 100,
                2,
            ),
            "penalty_total": sum(item["penalty"] for item in component_penalties.get(key, [])),
            "penalties": component_penalties.get(key, []),
        }
        for key, weight in applicable_profile_weights.items()
    ]
    profile_risk_items = sorted(
        [item for item in profile_fit_contributions if item["priority_score"] > 0],
        key=lambda item: item["priority_score"],
        reverse=True,
    )
    profile_next_focus = [item["component"] for item in profile_risk_items[:3]]
    profile_explanation = {
        "zh": "档案适配分只按已测硬指标和公开权重计算；它是用途适配参考，不替代健康度和发布门禁。",
        "en": "Profile fit is calculated only from measured hard metrics and the displayed weights; it is a delivery-fit reference, not a replacement for health or release gating.",
    }
    return {
        "score": score,
        "grade": grade,
        "score_basis": "hard_metrics_only",
        "asset_profile": profile,
        "profile_focus": profile_focus,
        "score_components": score_components,
        "score_component_penalties": component_penalties,
        "profile_fit_score": profile_fit_score,
        "profile_fit_weights": raw_profile_weights,
        "profile_fit_applicable_weights": applicable_profile_weights,
        "profile_fit_excluded_components": excluded_components,
        "profile_fit_component_status": component_status,
        "profile_fit_coverage": profile_coverage,
        "profile_fit_confidence": profile_confidence,
        "profile_fit_contributions": profile_fit_contributions,
        "profile_fit_risk_items": profile_risk_items[:5],
        "profile_fit_next_focus": profile_next_focus,
        "profile_fit_explanation": profile_explanation,
        "profile_fit_is_policy_weighted": True,
        "score_config_version": str(policy.get("config_version", "unknown")),
        "score_config_hash": scoring_config_hash(policy),
        "total_penalty": total_penalty,
        "penalties": penalties,
        "hard_checks": hard_checks,
        "soft_evaluation": soft_evaluation,
        "target_face_budget": target_face_budget,
        "effective_face_budget": budget,
        "disposition": disposition,
        "release_decision": release_decision,
    }
