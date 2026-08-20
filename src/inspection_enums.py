"""Shared status and severity vocabulary for inspection results.

The project has three related but different concepts:

* ``CheckStatus`` describes the outcome of a check.
* ``CoverageStatus`` describes how much of the asset was inspected.
* ``IssueStatus`` describes how an issue card should be prioritized in the UI.

Keeping these concepts separate prevents a check being marked as "checked"
and accidentally being interpreted as "passed".
"""

from __future__ import annotations

from enum import Enum
from typing import TypeVar


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SAMPLED = "sampled"
    NOT_CHECKED = "not_checked"
    NOT_APPLICABLE = "not_applicable"


class CoverageStatus(str, Enum):
    CHECKED = "checked"
    SAMPLED = "sampled"
    NOT_CHECKED = "not_checked"
    NOT_APPLICABLE = "not_applicable"


class IssueStatus(str, Enum):
    FAILED = "fail"
    ATTENTION = "attention"
    NEAR_THRESHOLD = "near_threshold"
    INFO = "info"
    PASSED = "pass"
    NOT_CHECKED = "not_checked"
    NOT_APPLICABLE = "not_applicable"


class Severity(str, Enum):
    BLOCKER = "blocker"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    NONE = "none"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    IMPORTING = "importing"
    INSPECTING = "inspecting"
    RENDERING = "rendering"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


EnumType = TypeVar("EnumType", bound=Enum)


def enum_values(enum_type: type[EnumType]) -> set[str]:
    """Return the serialized values accepted for an enum family."""
    return {item.value for item in enum_type}


def enum_value(value: object, enum_type: type[EnumType], default: EnumType) -> str:
    """Coerce a legacy/string value to an enum value without raising in UI code."""
    candidate = value.value if isinstance(value, Enum) else str(value)
    return candidate if candidate in enum_values(enum_type) else default.value
