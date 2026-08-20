"""Shared coverage-policy helpers for UI, scoring, and detector reports.

Coverage describes what was actually inspected.  It is intentionally kept
separate from pass/fail issue status so a material-only asset, a sampled
animation probe, or a runtime-only manifest cannot be mislabeled as fully
verified by one consumer and unverified by another.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from src.inspection_enums import CoverageStatus


MATERIAL_STAT_KEYS = (
    "material_count",
    "material_slot_count",
    "texture_image_count",
    "pbr_material_reports",
    "pbr_channel_issue_count",
)
RUNTIME_STAT_KEYS = (
    "loading_risk",
    "estimated_load_time_ms",
    "estimated_load_time_seconds",
    "estimated_texture_memory_bytes",
    "estimated_runtime_memory_bytes",
    "estimated_draw_calls",
    "draw_call_risk",
    "file_size_bytes",
    "texture_memory_bytes",
    "lod_count",
)


def _valid_number(value: Any, *, minimum: float = 0.0) -> bool:
    """Accept finite numeric metrics, including zero for legitimate counts."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= minimum
    )


def _valid_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value in {0, 1}
    return isinstance(value, str) and value.strip().lower() in {"true", "false", "yes", "no", "1", "0"}


def has_material_statistics(metadata: Mapping[str, Any]) -> bool:
    """Return whether a usable deterministic material statistic exists.

    Presence of a key alone is not enough: ``None`` and an empty report list
    commonly indicate a partial manifest rather than a completed check.
    Numeric zero remains valid because a material can legitimately have zero
    image textures or zero PBR issues.
    """
    numeric_keys = {
        "material_count", "material_slot_count", "texture_image_count",
        "pbr_channel_issue_count",
    }
    if any(_valid_number(metadata.get(key)) for key in numeric_keys if key in metadata):
        return True
    reports = metadata.get("pbr_material_reports")
    return isinstance(reports, (list, tuple)) and bool(reports)


def has_runtime_statistics(metadata: Mapping[str, Any]) -> bool:
    """Return whether a usable deterministic runtime statistic exists."""
    numeric_keys = {
        "estimated_load_time_ms", "estimated_load_time_seconds",
        "estimated_texture_memory_bytes", "estimated_runtime_memory_bytes",
        "estimated_draw_calls", "texture_memory_bytes", "lod_count",
    }
    if any(_valid_number(metadata.get(key)) for key in numeric_keys if key in metadata):
        return True
    if "file_size_bytes" in metadata and _valid_number(metadata.get("file_size_bytes"), minimum=1):
        return True
    return (
        str(metadata.get("loading_risk", "")).strip().lower() in {"low", "medium", "high"}
        or str(metadata.get("draw_call_risk", "")).strip().lower() in {"low", "medium", "high"}
    )


def animation_is_present(metadata: Mapping[str, Any]) -> bool:
    """Return whether the asset contains a rig or animation that needs review."""
    return any(_valid_flag(metadata.get(key)) and str(metadata.get(key)).strip().lower() not in {"false", "no", "0"}
               for key in ("source_has_armature", "source_has_animation"))


def animation_coverage_status(metadata: Mapping[str, Any]) -> str:
    """Classify animation coverage, distinguishing sampled deformation probes."""
    if not animation_is_present(metadata):
        return CoverageStatus.NOT_APPLICABLE.value
    inspection_status = str(metadata.get("animation_inspection_status", "") or "")
    if inspection_status == "sampled_pose" or int(metadata.get("deformation_self_intersection_sample_count", 0) or 0) > 0:
        return CoverageStatus.SAMPLED.value
    if inspection_status == "binding_only":
        return CoverageStatus.CHECKED.value
    if inspection_status == "not_checked":
        return CoverageStatus.NOT_CHECKED.value
    # Legacy manifests did not have the explicit inspection status. Keep the
    # old sampled signal, but do not call a zero-frame animation result fully
    # checked unless a binding statistic proves that a rigged mesh existed.
    if int(metadata.get("rigged_mesh_count", 0) or 0) > 0 and not metadata.get("source_has_animation"):
        return CoverageStatus.CHECKED.value
    if metadata.get("animation_playability") in {"not_applicable", "not_tested_no_actions", "not_tested_no_rigged_mesh"}:
        return CoverageStatus.NOT_CHECKED.value
    return CoverageStatus.CHECKED.value
