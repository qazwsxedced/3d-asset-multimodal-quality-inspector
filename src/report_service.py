"""Standalone HTML report generation for inspection results."""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

from src.inspection_result import InspectionResult


AUDIT_SCHEMA_VERSION = "1.0"


def data_uri(path: str | None) -> str:
    if not path or not Path(path).exists():
        return ""
    file_path = Path(path)
    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_structured_audit(result: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical machine-readable audit payload used by exports."""
    model = InspectionResult.from_legacy(result)
    errors = model.validate()
    if errors:
        details = "\n".join(f"- {error}" for error in errors[:20])
        suffix = "\n- ..." if len(errors) > 20 else ""
        raise ValueError(f"Invalid inspection result; audit export aborted:\n{details}{suffix}")
    payload = model.to_dict()
    payload["audit_schema_version"] = AUDIT_SCHEMA_VERSION
    payload["feedback_language"] = result.get("feedback_language")
    return payload


def _audit_filename(result: dict[str, Any], suffix: str, timestamp: int | None = None) -> str:
    provenance = result.get("provenance", {}) or {}
    task_id = str(provenance.get("task_id", result.get("sample_id", "inspection")))
    stamp = timestamp if timestamp is not None else time.time_ns()
    return f"{result.get('sample_id', 'asset')}_{task_id}_{stamp}.{suffix}"


def write_json_audit(result: dict[str, Any], output_dir: Path) -> str:
    """Write the canonical audit payload as a downloadable JSON artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / _audit_filename(result, "json")
    audit_path.write_text(
        json.dumps(build_structured_audit(result), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(audit_path)


def write_html_report(
    result: dict[str, Any],
    paths: dict[str, Any],
    summary_html: str,
    issue_html: str,
    comparison_html: str,
    output_dir: Path,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = result.get("provenance", {}) or {}
    # Nanosecond precision prevents a second inspection from overwriting a
    # previous report when the same sample is run repeatedly in one second.
    report_path = output_dir / _audit_filename(result, "html")
    cards = "".join(
        f'<img src="{data_uri(path)}" alt="view {idx}" style="width:23%;margin:0.5%;border-radius:8px;">'
        for idx, path in enumerate(paths.get("views", []))
        if path and Path(path).exists()
    )
    diagnostics = "".join(
        f'<div style="display:inline-block;width:48%;vertical-align:top;"><h3>{name}</h3><img src="{data_uri(path)}" style="max-width:100%;border-radius:8px;"></div>'
        for name, path in (("UV layout", paths.get("uv")), ("UV stretch heatmap", paths.get("uv_heatmap")), ("Normal diagnostic", paths.get("normal")))
        if path and Path(path).exists()
    )
    overlay_path = paths.get("model_overlay")
    if overlay_path and Path(overlay_path).exists():
        overlay_uri = data_uri(overlay_path)
        diagnostics += (
            "<div style='display:inline-block;width:48%;vertical-align:top;'>"
            "<h3>Issue overlay (3D)</h3>"
            "<p>This artifact is a GLB model, not a raster image. "
            f"<a download='issue_overlay.glb' href='{overlay_uri}'>Download 3D overlay</a> "
            "and open it in a GLB viewer.</p></div>"
        )
    locator_path = paths.get("issue_locator")
    if locator_path and Path(locator_path).exists():
        locator_uri = data_uri(locator_path)
        diagnostics += (
            "<div style='display:inline-block;width:48%;vertical-align:top;'>"
            "<h3>Issue locator data</h3>"
            f"<a download='issue_locator.json' href='{locator_uri}'>Download object/face locator JSON</a>"
            "</div>"
        )
    selection_script_path = paths.get("issue_selection_script")
    if selection_script_path and Path(selection_script_path).exists():
        selection_script_uri = data_uri(selection_script_path)
        diagnostics += (
            "<div style='display:inline-block;width:48%;vertical-align:top;'>"
            "<h3>Blender face selection</h3>"
            "<p>Open the original asset in Blender, open this script in the Text Editor, and run it. "
            f"<a download='apply_issue_locator.py' href='{selection_script_uri}'>Download Blender face-selection script</a>"
            "</p></div>"
        )
    language = result.get("feedback_language", "中文")
    structured = build_structured_audit(result)
    problems_title = "问题卡片" if language == "中文" else "Problems"
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>3D Quality Report</title>
    <style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#172033}} pre{{background:#f4f6f8;padding:16px;border-radius:8px;overflow:auto;white-space:pre-wrap}} summary{{cursor:pointer}}</style></head>
    <body><h1>3D Asset Multimodal Quality Report</h1><p><b>Asset:</b> {html.escape(str(result.get('asset_id', '—')))} &nbsp; <b>Mode:</b> {html.escape(str(result.get('mode', '—')))}</p>
    <h2>{'决策摘要' if language == '中文' else 'Decision summary'}</h2>{summary_html}<h2>{problems_title}</h2>{issue_html}{comparison_html}
    <h2>Multi-view evidence</h2><div>{cards}</div><h2>Diagnostic evidence</h2><div>{diagnostics}</div>
    <details style='margin-top:20px'><summary><b>Provenance</b></summary><pre>{html.escape(json.dumps(provenance, ensure_ascii=False, indent=2, default=str))}</pre></details>
    <details style='margin-top:20px'><summary><b>Structured audit data</b></summary><pre>{html.escape(json.dumps(structured, ensure_ascii=False, indent=2, default=str))}</pre></details>
    </body></html>"""
    report_path.write_text(body, encoding="utf-8")
    return str(report_path)
