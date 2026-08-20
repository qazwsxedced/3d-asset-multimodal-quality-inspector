"""Validated, shared inspection-threshold configuration.

The web app and Blender worker must interpret the same threshold file. This
module rejects unknown keys and invalid ranges before a task starts, while the
low-level loader still falls back to safe defaults for direct Blender calls.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping


DEFAULT_THRESHOLDS: dict[str, int | float] = {
    "max_faces": 50_000,
    "max_uv_overlap_ratio": 0.001,
    "max_triangle_aspect_p95": 8.0,
    "max_texture_size": 4096,
    "min_texture_size": 512,
    "max_material_slots": 8,
    "max_draw_calls": 100,
    "max_texture_memory_bytes": 1_073_741_824,
    "max_estimated_load_time_seconds": 8.0,
    "max_influences_per_vertex": 4,
    "weight_sum_tolerance": 0.05,
    "max_unbound_vertex_ratio": 0.01,
    "max_weight_error_ratio": 0.01,
    "max_material_slots_per_object": 8,
    "max_diagnostic_triangles": 50_000,
    "max_component_gap_pairs": 200_000,
    "max_upload_size_bytes": 2_147_483_648,
    "job_timeout_seconds": 600,
    "preview_views": 4,
    "preview_resolution": 192,
}


# type, minimum, maximum; ``None`` means unbounded on that side.
_SCHEMA: dict[str, tuple[str, float | None, float | None]] = {
    "max_faces": ("integer", 1, None),
    "max_uv_overlap_ratio": ("number", 0, 1),
    "max_triangle_aspect_p95": ("number", 0.000001, None),
    "max_texture_size": ("integer", 1, None),
    "min_texture_size": ("integer", 1, None),
    "max_material_slots": ("integer", 0, None),
    "max_draw_calls": ("integer", 0, None),
    "max_texture_memory_bytes": ("integer", 0, None),
    "max_estimated_load_time_seconds": ("number", 0, None),
    "max_influences_per_vertex": ("integer", 0, None),
    "weight_sum_tolerance": ("number", 0, 1),
    "max_unbound_vertex_ratio": ("number", 0, 1),
    "max_weight_error_ratio": ("number", 0, 1),
    "max_material_slots_per_object": ("integer", 0, None),
    "max_diagnostic_triangles": ("integer", 1, None),
    "max_component_gap_pairs": ("integer", 1, None),
    "max_upload_size_bytes": ("integer", 1, None),
    "job_timeout_seconds": ("integer", 1, None),
    "preview_views": ("integer", 1, 8),
    "preview_resolution": ("integer", 64, 4096),
}


def _valid_number(value: Any, kind: str) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(float(value)):
        return False
    return kind == "number" or isinstance(value, int)


def validate_thresholds(config: Mapping[str, Any]) -> list[str]:
    """Return human-readable validation errors; an empty list means valid."""
    if not isinstance(config, Mapping):
        return ["configuration root must be a JSON object"]
    errors: list[str] = []
    unknown = sorted(set(config) - set(_SCHEMA))
    errors.extend(f"unknown key: {key}" for key in unknown)
    for key, (kind, minimum, maximum) in _SCHEMA.items():
        if key not in config:
            continue
        value = config[key]
        if not _valid_number(value, kind):
            errors.append(f"{key}: expected {kind}")
            continue
        numeric = float(value)
        if minimum is not None and numeric < minimum:
            errors.append(f"{key}: must be >= {minimum:g}")
        if maximum is not None and numeric > maximum:
            errors.append(f"{key}: must be <= {maximum:g}")
    if "min_texture_size" in config and "max_texture_size" in config:
        if _valid_number(config["min_texture_size"], "integer") and _valid_number(config["max_texture_size"], "integer"):
            if config["min_texture_size"] > config["max_texture_size"]:
                errors.append("min_texture_size: must be <= max_texture_size")
    return errors


def validate_threshold_file(path: Path | str) -> list[str]:
    """Validate a JSON file and include its path in actionable errors."""
    path = Path(path)
    if not path.exists():
        return [f"threshold config not found: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"threshold config cannot be read: {exc}"]
    return validate_thresholds(payload)


def load_thresholds(path: Path | str) -> dict[str, int | float]:
    """Load a valid config or return a complete safe default set."""
    path = Path(path)
    if not path.exists():
        return dict(DEFAULT_THRESHOLDS)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return dict(DEFAULT_THRESHOLDS)
    errors = validate_thresholds(payload)
    if errors:
        return dict(DEFAULT_THRESHOLDS)
    return {**DEFAULT_THRESHOLDS, **{key: payload[key] for key in _SCHEMA if key in payload}}
