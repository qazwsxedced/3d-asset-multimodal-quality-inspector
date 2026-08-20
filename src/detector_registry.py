"""Small, deterministic detector plug-in registry.

Detectors are intentionally independent from Gradio and Blender.  A detector
receives a read-only context and returns a serializable report.  This keeps
new checks from becoming another branch in the UI callback and makes them
usable by reports, batch jobs, and tests.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from src.coverage_policy import (
    animation_coverage_status,
    has_material_statistics,
    has_runtime_statistics,
)


@dataclass(frozen=True)
class DetectorContext:
    metadata: Mapping[str, Any]
    thresholds: Mapping[str, Any]
    asset_profile: str = "Auto"
    target_face_budget: str = "Auto"


Detector = Callable[[DetectorContext], dict[str, Any]]


@dataclass
class DetectorRegistry:
    _detectors: dict[str, Detector] = field(default_factory=dict)

    def register(self, name: str, detector: Detector | None = None):
        """Register a detector directly or use ``@registry.register(name)``."""
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("Detector name cannot be empty.")

        def add(function: Detector) -> Detector:
            if normalized in self._detectors:
                raise ValueError(f"Detector already registered: {normalized}")
            self._detectors[normalized] = function
            return function

        return add(detector) if detector is not None else add

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._detectors))

    def run(self, context: DetectorContext) -> dict[str, dict[str, Any]]:
        reports: dict[str, dict[str, Any]] = {}
        for name in self.names():
            report = self._detectors[name](context)
            if not isinstance(report, dict):
                raise TypeError(f"Detector {name!r} must return a dict.")
            reports[name] = dict(report)
        return reports

    def load_plugins(self, locations: Iterable[str | Path]) -> list[dict[str, Any]]:
        """Load optional detector modules without making them UI dependencies.

        A plug-in can expose ``register_detectors(registry)``.  Import errors
        are returned as structured records so a bad optional detector cannot
        prevent the baseline inspection page from starting.
        """
        results: list[dict[str, Any]] = []
        for location in locations:
            path = Path(location).expanduser().resolve()
            if not path.exists() or not path.is_file() or path.suffix.lower() != ".py":
                continue
            before = set(self._detectors)
            try:
                module_name = f"asset_inspector_plugin_{path.stem}_{abs(hash(path))}"
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    raise ImportError("Unable to create an import specification.")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                callback = getattr(module, "register_detectors", None)
                if callback is not None:
                    callback(self)
                results.append({
                    "path": str(path),
                    "status": "loaded",
                    "detectors": sorted(set(self._detectors) - before),
                })
            except Exception as exc:  # Optional plug-ins must fail soft.
                # A plug-in may register several detectors before raising.
                # Roll those registrations back so a failed module cannot
                # leave the registry in a partially initialized state.
                for name in set(self._detectors) - before:
                    self._detectors.pop(name, None)
                results.append({
                    "path": str(path),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "detectors": [],
                })
        return results


def _geometry_detector(context: DetectorContext) -> dict[str, Any]:
    metadata = context.metadata
    defects = [
        defect for defect in (
            "non_manifold", "hole", "degenerate_faces", "flipped_normals", "stretched_triangles",
        ) if defect in metadata.get("detected_defects", [])
    ]
    return {
        "status": "failed" if defects else "checked",
        "defects": defects,
        "triangle_count": metadata.get("triangle_count", metadata.get("face_count")),
        "vertex_count": metadata.get("vertex_count"),
    }


def _uv_detector(context: DetectorContext) -> dict[str, Any]:
    metadata = context.metadata
    return {
        "status": "sampled" if metadata.get("uv_analysis_sampled") or metadata.get("uv_overlap_analysis_sampled") else ("checked" if metadata.get("uv_layer_count") else "not_checked"),
        "overlap_ratio": metadata.get("uv_overlap_ratio", 0.0),
        "stretch_p95": (metadata.get("uv_stretch_stats") or {}).get("p95"),
        "density": metadata.get("uv_density_stats", {}),
    }


def _materials_detector(context: DetectorContext) -> dict[str, Any]:
    metadata = context.metadata
    return {
        "status": "checked" if has_material_statistics(metadata) else "not_checked",
        "material_count": metadata.get("material_count"),
        "pbr_issue_count": metadata.get("pbr_channel_issue_count", 0),
        "missing_texture_count": metadata.get("missing_texture_count", 0),
    }


def _runtime_detector(context: DetectorContext) -> dict[str, Any]:
    metadata = context.metadata
    return {
        "status": "checked" if has_runtime_statistics(metadata) else "not_checked",
        "loading_risk": metadata.get("loading_risk"),
        "estimated_load_time_seconds": metadata.get("estimated_load_time_seconds"),
        "estimated_draw_calls": metadata.get("estimated_draw_calls"),
    }


def _animation_detector(context: DetectorContext) -> dict[str, Any]:
    metadata = context.metadata
    return {
        "status": animation_coverage_status(metadata),
        "armature_count": metadata.get("source_armature_count", 0),
        "action_count": metadata.get("animation_action_count", 0),
        "rig_issue_count": sum(int(metadata.get(key, 0) or 0) for key in ("unbound_vertex_count", "weight_sum_error_count", "over_influenced_vertex_count")),
    }


DEFAULT_DETECTOR_REGISTRY = DetectorRegistry()
DEFAULT_DETECTOR_REGISTRY.register("animation", _animation_detector)
DEFAULT_DETECTOR_REGISTRY.register("geometry", _geometry_detector)
DEFAULT_DETECTOR_REGISTRY.register("materials", _materials_detector)
DEFAULT_DETECTOR_REGISTRY.register("runtime", _runtime_detector)
DEFAULT_DETECTOR_REGISTRY.register("uv", _uv_detector)
