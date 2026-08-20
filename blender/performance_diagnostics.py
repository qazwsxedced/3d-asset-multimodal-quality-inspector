"""Runtime delivery and loading-performance estimates."""

from __future__ import annotations

from pathlib import Path

from inspection_config import load_thresholds

DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[1] / "config" / "inspection_thresholds.json"

def performance_diagnostics(input_path: Path, inventory: dict, texture: dict, geometry: dict, thresholds: dict | None = None) -> dict:
    """Estimate delivery and loading risk using explicit, inspectable heuristics."""
    thresholds = thresholds or load_thresholds(DEFAULT_THRESHOLDS)
    file_size = int(input_path.stat().st_size) if input_path.exists() else 0
    texture_bytes = int(texture.get("texture_total_bytes", 0) or 0)
    texture_memory = int(texture.get("texture_memory_bytes_estimated", 0) or 0)
    mesh_objects = int(inventory.get("source_mesh_object_count", 0) or 0)
    material_count = int(texture.get("unique_material_count", 0) or 0)
    source_meshes = inventory.get("source_mesh_objects", []) or []
    # A more useful draw-call estimate is per-object material usage, rather
    # than object_count multiplied by the scene-wide unique material count.
    draw_call_estimate = sum(max(1, int(item.get("material_slot_count", 0) or 0)) for item in source_meshes)
    draw_call_estimate = max(1, draw_call_estimate or mesh_objects or material_count)
    memory_bytes = texture_memory + int(geometry.get("vertex_count", 0) * 32) + int(geometry.get("triangle_count", 0) * 16)
    estimated_seconds = file_size / (50 * 1024 * 1024) + texture_memory / (250 * 1024 * 1024) + draw_call_estimate * 0.015
    if texture_memory > int(thresholds["max_texture_memory_bytes"]) or draw_call_estimate > int(thresholds["max_draw_calls"]) or estimated_seconds > float(thresholds["max_estimated_load_time_seconds"]):
        risk = "high"
    elif texture_memory > int(thresholds["max_texture_memory_bytes"]) * 0.5 or draw_call_estimate > int(thresholds["max_draw_calls"]) * 0.4 or estimated_seconds > float(thresholds["max_estimated_load_time_seconds"]) * 0.375:
        risk = "medium"
    else:
        risk = "low"
    return {
        "asset_file_size_bytes": file_size,
        "texture_total_bytes": texture_bytes,
        "estimated_texture_memory_bytes": texture_memory,
        "estimated_runtime_memory_bytes": memory_bytes,
        "estimated_draw_calls": draw_call_estimate,
        "draw_call_risk": "high" if draw_call_estimate > 100 else "medium" if draw_call_estimate > 40 else "low",
        "estimated_load_time_seconds": round(estimated_seconds, 2),
        "loading_risk": risk,
        "lod_count": inventory.get("source_lod_count", 0),
        "lod_levels": inventory.get("source_lod_levels", []),
        "lod_missing_levels": inventory.get("source_lod_missing_levels", []),
        "vertex_count_for_performance": geometry.get("vertex_count", 0),
        "source_bone_count": inventory.get("source_bone_count", 0),
        "source_morph_target_count": inventory.get("source_morph_target_count", 0),
        "animation_present": inventory.get("source_has_animation", False),
        "armature_present": inventory.get("source_has_armature", False),
    }
