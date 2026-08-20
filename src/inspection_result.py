"""Canonical inspection result model shared by UI, reports, and integrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Mapping, TypeVar

from src.inspection_enums import CoverageStatus, enum_values
from src.inspection_schema import normalize_issue_list, validate_issue


RESULT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class AssetInfo:
    asset_id: str | None = None
    sample_id: str | None = None
    source_file: str | None = None
    source_format: str | None = None
    generalization: str | None = None
    question_type: str | None = None


@dataclass(frozen=True)
class _SectionResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    status: str = CoverageStatus.NOT_CHECKED.value
    coverage: str = CoverageStatus.NOT_CHECKED.value
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeometryResult(_SectionResult):
    pass


@dataclass(frozen=True)
class UVResult(_SectionResult):
    pass


@dataclass(frozen=True)
class MaterialResult(_SectionResult):
    pass


@dataclass(frozen=True)
class AnimationResult(_SectionResult):
    pass


@dataclass(frozen=True)
class RuntimeResult(_SectionResult):
    pass


@dataclass(frozen=True)
class ScoreResult:
    health: dict[str, Any] = field(default_factory=dict)
    release_decision: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Provenance:
    values: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)


ModelType = TypeVar("ModelType", bound="InspectionResult")


@dataclass(frozen=True)
class InspectionResult:
    """Typed result envelope with a compatibility constructor for legacy rows."""

    schema_version: str
    asset: AssetInfo
    geometry: GeometryResult
    uv: UVResult
    materials: MaterialResult
    animation: AnimationResult
    runtime: RuntimeResult
    issues: list[dict[str, Any]] = field(default_factory=list)
    score: ScoreResult = field(default_factory=ScoreResult)
    provenance: Provenance = field(default_factory=Provenance)
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    mode: str | None = None
    condition: str | None = None
    selected_source: str | None = None
    agreement_score: float | None = None
    review_required: bool = False
    disagreement_reasons: list[str] = field(default_factory=list)
    rule_result: dict[str, Any] | None = None
    vlm_result: dict[str, Any] | None = None
    soft_inputs: dict[str, Any] = field(default_factory=dict)
    comparison: str = ""

    SECTION_TYPES: ClassVar[dict[str, type[_SectionResult]]] = {
        "geometry": GeometryResult,
        "uv": UVResult,
        "materials": MaterialResult,
        "animation": AnimationResult,
        "runtime": RuntimeResult,
    }

    def validate(self) -> list[str]:
        """Return structural errors before a result is exported or published."""
        errors: list[str] = []
        if self.schema_version != RESULT_SCHEMA_VERSION:
            errors.append(f"schema_version must be {RESULT_SCHEMA_VERSION}")
        coverage_values = enum_values(CoverageStatus)
        for name in self.SECTION_TYPES:
            section = getattr(self, name)
            if not isinstance(section.metrics, dict):
                errors.append(f"{name}.metrics must be an object")
            if section.status not in coverage_values:
                errors.append(f"{name}.status must be a coverage status")
            if section.coverage not in coverage_values:
                errors.append(f"{name}.coverage must be a coverage status")
        for index, issue in enumerate(self.issues):
            errors.extend(f"issues[{index}].{error}" for error in validate_issue(issue))
        return errors

    @classmethod
    def from_legacy(cls: type[ModelType], result: Mapping[str, Any]) -> ModelType:
        """Build the typed envelope from the current nested-dict result."""
        metadata = dict(result.get("metadata", {}) or {})
        selected = dict(result.get("selected_result", {}) or {})
        staging = dict(metadata.get("asset_staging", {}) or {})
        source_file = staging.get("source_file")
        source_format = Path(str(source_file)).suffix.lower().lstrip(".") if source_file else None
        coverage = dict(selected.get("inspection_coverage", {}) or {})
        coverage_details = dict(selected.get("inspection_coverage_details", {}) or {})

        sections = {
            "geometry": cls._section(
                GeometryResult,
                metadata,
                coverage,
                coverage_details,
                "geometry",
                ("vertex_", "face_", "triangle_", "boundary_", "non_manifold", "degenerate_", "flipped_", "loose_", "connected_", "component_", "source_mesh_", "source_object_", "ngon_"),
            ),
            "uv": cls._section(
                UVResult,
                metadata,
                coverage,
                coverage_details,
                "uv",
                ("uv_",),
            ),
            "materials": cls._section(
                MaterialResult,
                metadata,
                coverage,
                coverage_details,
                "materials",
                ("material", "texture", "pbr_", "missing_texture", "low_resolution_texture"),
            ),
            "animation": cls._section(
                AnimationResult,
                metadata,
                coverage,
                coverage_details,
                "animation",
                ("animation", "armature", "rig", "rigged", "weight", "influence", "deformation", "unbound", "over_influenced"),
            ),
            "runtime": cls._section(
                RuntimeResult,
                metadata,
                coverage,
                coverage_details,
                "runtime",
                ("loading", "estimated_", "draw_call", "file_size", "texture_memory", "lod", "asset_"),
            ),
        }
        health = dict(selected.get("health_score", {}) or {})
        release_decision = dict(result.get("release_decision", {}) or health.get("release_decision", {}) or {})
        confidence = dict(selected.get("confidence_report", {}) or {})
        asset = AssetInfo(
            asset_id=result.get("asset_id"),
            sample_id=result.get("sample_id"),
            source_file=source_file,
            source_format=source_format,
            generalization=result.get("generalization"),
            question_type=result.get("question_type"),
        )
        return cls(
            schema_version=RESULT_SCHEMA_VERSION,
            asset=asset,
            geometry=sections["geometry"],
            uv=sections["uv"],
            materials=sections["materials"],
            animation=sections["animation"],
            runtime=sections["runtime"],
            issues=normalize_issue_list(selected.get("issues", []) or [], metadata),
            score=ScoreResult(health=health, release_decision=release_decision, confidence=confidence),
            provenance=Provenance(dict(result.get("provenance", {}) or {})),
            artifacts=dict(result.get("artifacts", {}) or {}),
            metadata=metadata,
            mode=result.get("mode"),
            condition=result.get("condition"),
            selected_source=result.get("selected_source"),
            agreement_score=result.get("agreement_score"),
            review_required=bool(result.get("review_required", False)),
            disagreement_reasons=list(result.get("disagreement_reasons", []) or []),
            rule_result=result.get("rule_result"),
            vlm_result=result.get("vlm_result"),
            soft_inputs=dict(result.get("soft_inputs", {}) or {}),
            comparison=str(result.get("comparison", "") or ""),
        )

    @staticmethod
    def _section(
        section_type: type[_SectionResult],
        metadata: dict[str, Any],
        coverage: dict[str, Any],
        coverage_details: dict[str, Any],
        coverage_key: str,
        prefixes: tuple[str, ...],
    ) -> _SectionResult:
        metrics = {
            key: value
            for key, value in metadata.items()
            if any(key.startswith(prefix) or prefix in key for prefix in prefixes)
        }
        raw_coverage = str(coverage.get(coverage_key, CoverageStatus.NOT_CHECKED.value))
        # The legacy UI adds sampling evidence after the enum value, e.g.
        # ``sampled:50000/96999 (51.5%)``. Keep that evidence in details while
        # exposing a stable enum value to reports and downstream consumers.
        if raw_coverage.startswith(CoverageStatus.SAMPLED.value):
            section_coverage = CoverageStatus.SAMPLED.value
        elif raw_coverage.startswith(CoverageStatus.CHECKED.value):
            section_coverage = CoverageStatus.CHECKED.value
        elif raw_coverage.startswith(CoverageStatus.NOT_APPLICABLE.value):
            section_coverage = CoverageStatus.NOT_APPLICABLE.value
        else:
            section_coverage = CoverageStatus.NOT_CHECKED.value
        status = section_coverage
        details = coverage_details.get(coverage_key, {})
        if not isinstance(details, dict):
            details = {"value": details}
        details = dict(details)
        if raw_coverage != section_coverage:
            details.setdefault("legacy_coverage_text", raw_coverage)
        return section_type(metrics=metrics, status=status, coverage=section_coverage, details=details)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the canonical model without depending on Gradio or Blender."""
        payload = asdict(self)
        payload["provenance"] = self.provenance.to_dict()
        return payload
