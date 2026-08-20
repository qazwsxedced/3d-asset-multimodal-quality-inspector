"""Shared, dependency-free schemas for inspection issues.

The UI, HTML report, JSON audit record, and optional VLM layer all consume
the same normalized issue shape. Keeping this module independent of Gradio
and Blender makes it safe to reuse from CLI and API entry points.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from src.inspection_enums import IssueStatus, Severity, enum_values


ISSUE_SCHEMA_VERSION = "1.0"
ISSUE_STATUSES = enum_values(IssueStatus)
SEVERITIES = enum_values(Severity)


def _category_from_id(issue_id: str) -> str:
    prefix = issue_id.split(":", 1)[0] if ":" in issue_id else "issue"
    return {"defect": "geometry", "warning": "asset", "threshold": "threshold"}.get(prefix, prefix)


def normalize_issue(issue: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a legacy issue dictionary without breaking existing renderers."""
    normalized = dict(issue)
    issue_id = str(normalized.get("issue_id", "issue:unknown"))
    status = str(normalized.get("status", IssueStatus.INFO.value))
    severity = str(normalized.get("severity", Severity.INFO.value))
    if status not in ISSUE_STATUSES:
        status = IssueStatus.INFO.value
    if severity not in SEVERITIES:
        severity = Severity.INFO.value

    locator = dict(normalized.get("location") or normalized.get("locator") or {})
    source_breakdown = (metadata or {}).get("source_issue_breakdown", []) or []
    face_index_map = (metadata or {}).get("issue_related_face_indices", {}) or {}
    defect = issue_id.split(":", 1)[1] if ":" in issue_id else issue_id
    object_rows = []
    for row in source_breakdown:
        counts = row.get("related_face_counts", {}) or {}
        if int(counts.get(defect, 0) or 0) > 0:
            object_rows.append({
                "object_name": str(row.get("object_name", "—")),
                "related_face_count": int(counts.get(defect, 0) or 0),
                "face_indices": list((row.get("related_face_indices", {}) or {}).get(defect, []) or []),
                "face_index_space": str(row.get("face_index_space", "source_mesh_base")),
                "object_selector": dict(row.get("object_selector") or {}),
            })
    object_rows.sort(key=lambda row: row["related_face_count"], reverse=True)
    if object_rows:
        locator.setdefault("object_names", [row["object_name"] for row in object_rows[:8]])
        locator.setdefault("object_count", len(object_rows))
        locator.setdefault("objects", object_rows[:8])
        locator.setdefault("face_index_space", object_rows[0].get("face_index_space", "source_mesh_base"))
        locator.setdefault("identity_validation", "object_name_then_topology_fingerprint")

    material_details = normalized.get("material_details", []) or []
    if material_details:
        material_names = [
            str(item.get("material_name", item.get("material", item.get("name", "—"))))
            for item in material_details
            if isinstance(item, dict)
        ]
        if material_names:
            locator.setdefault("material_names", material_names[:8])
        material_objects = sorted({
            str(object_name)
            for item in material_details
            if isinstance(item, dict)
            for object_name in item.get("object_names", []) or []
        })
        if material_objects:
            locator.setdefault("object_names", material_objects[:8])
            locator.setdefault("object_count", len(material_objects))
            locator.setdefault("objects", [
                object_item
                for detail in material_details
                if isinstance(detail, dict)
                for object_item in detail.get("objects", []) or []
            ][:32])

    if defect in face_index_map:
        locator.setdefault("face_indices", list(face_index_map.get(defect, []) or []))
        locator.setdefault("face_index_count", int((metadata or {}).get("issue_related_face_counts", {}).get(defect, 0) or 0))
        locator.setdefault("face_index_truncated", bool((metadata or {}).get("issue_face_index_truncated", {}).get(defect, False)))

    normalized.update({
        "schema_version": ISSUE_SCHEMA_VERSION,
        "category": str(normalized.get("category", _category_from_id(issue_id))),
        "severity": severity,
        "status": status,
        "blocking": bool(normalized.get("blocking", False)),
        "impact": {
            "zh": str(normalized.get("impact_zh", "")),
            "en": str(normalized.get("impact_en", "")),
        },
        "fix": {
            "zh": str(normalized.get("fix_zh", "")),
            "en": str(normalized.get("fix_en", "")),
        },
        "recheck": {
            "zh": str(normalized.get("recheck_zh", "")),
            "en": str(normalized.get("recheck_en", "")),
        },
        # These keys are always present in the canonical protocol. ``None``
        # means the detector did not define a numeric threshold for this
        # informational card; it must not be confused with a missing field.
        "current_value": normalized.get("current_value"),
        "threshold": normalized.get("threshold"),
        "evidence": str(normalized.get("evidence", "")),
        "location": locator,
        # Keep the original key for backwards-compatible HTML/UI consumers.
        "locator": locator,
    })
    return normalized


def validate_issue(issue: Mapping[str, Any]) -> list[str]:
    """Return structural errors for one canonical issue record."""
    errors: list[str] = []
    if not isinstance(issue, Mapping):
        return ["issue must be an object"]
    issue_id = issue.get("issue_id")
    if not isinstance(issue_id, str) or not issue_id.strip():
        errors.append("issue_id must be a non-empty string")
    if issue.get("schema_version") != ISSUE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ISSUE_SCHEMA_VERSION}")
    if issue.get("status") not in ISSUE_STATUSES:
        errors.append(f"status must be one of {sorted(ISSUE_STATUSES)}")
    if issue.get("severity") not in SEVERITIES:
        errors.append(f"severity must be one of {sorted(SEVERITIES)}")
    if not isinstance(issue.get("blocking"), bool):
        errors.append("blocking must be boolean")
    for key in ("current_value", "threshold", "evidence"):
        if key not in issue:
            errors.append(f"missing field: {key}")
    for key in ("impact", "fix", "recheck"):
        value = issue.get(key)
        if not isinstance(value, Mapping):
            errors.append(f"{key} must be an object")
            continue
        for language in ("zh", "en"):
            if not isinstance(value.get(language), str):
                errors.append(f"{key}.{language} must be a string")
    if not isinstance(issue.get("location"), Mapping):
        errors.append("location must be an object")
    return errors


def normalize_issue_list(issues: Iterable[dict[str, Any]], metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return stable, canonical issue records while preserving UI-specific fields."""
    normalized = [normalize_issue(issue, metadata) for issue in issues]
    seen: set[str] = set()
    for index, issue in enumerate(normalized):
        issue_id = str(issue.get("issue_id", "issue:unknown"))
        if issue_id in seen:
            issue["issue_id"] = f"{issue_id}#{index + 1}"
        seen.add(str(issue["issue_id"]))
    return normalized
