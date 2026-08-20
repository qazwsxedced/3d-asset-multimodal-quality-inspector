"""Reproducibility and audit metadata for inspection results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DETECTOR_VERSION = "3d-asset-inspector-local-1"


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_provenance(
    manifest: Path,
    threshold_config: Path,
    metadata: dict[str, Any],
    mode: str,
    condition: str,
    scoring_config: Path | None = None,
) -> dict[str, Any]:
    """Build stable audit fields without requiring a Git checkout."""
    manifest = manifest.expanduser().resolve()
    threshold_config = threshold_config.expanduser().resolve()
    scoring_config = (scoring_config or Path(__file__).resolve().parents[1] / "config" / "inspection_scoring.json").expanduser().resolve()
    staging = metadata.get("asset_staging", {}) or {}
    runtime_threshold_config = manifest.parent / "inspection_thresholds.runtime.json"
    effective_threshold_config = runtime_threshold_config if runtime_threshold_config.exists() else threshold_config
    return {
        "task_id": manifest.parent.name,
        "detected_at_utc": datetime.now(timezone.utc).isoformat(),
        "detector_version": DETECTOR_VERSION,
        "mode": mode,
        "condition": condition,
        "manifest_path": str(manifest),
        "threshold_config_path": str(threshold_config),
        "threshold_config_sha256": file_sha256(threshold_config),
        "effective_threshold_config_path": str(effective_threshold_config),
        "effective_threshold_config_sha256": file_sha256(effective_threshold_config),
        "scoring_config_path": str(scoring_config),
        "scoring_config_sha256": file_sha256(scoring_config),
        "input_file": staging.get("source_file"),
        "input_sha256": staging.get("source_sha256"),
        "input_size_bytes": staging.get("source_size_bytes"),
        "staging_warnings": list(staging.get("warnings", []) or []),
    }


def provenance_json(provenance: dict[str, Any]) -> str:
    return json.dumps(provenance, ensure_ascii=False, indent=2)
