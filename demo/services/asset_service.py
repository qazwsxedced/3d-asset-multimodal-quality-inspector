"""Upload, staging, repair, and runtime-asset preparation service."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.asset_staging import stage_asset
from src.data_protocol import compact_metadata
from src.runtime_artifacts import validate_runtime_artifacts


@dataclass(frozen=True)
class AssetDependencies:
    run_blender_job: Callable[..., Path]
    find_blender: Callable[[], str]
    resolve_threshold_path: Callable[[str | None], Path]
    load_thresholds: Callable[[Path], dict[str, Any]]
    choose_adaptive_inspection_settings: Callable[[Path, dict[str, Any]], dict[str, Any]]
    write_runtime_inspection_metadata: Callable[..., None]
    load_rows: Callable[[Path], tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]]
    resolve_image_paths: Callable[[dict[str, Any], Path], dict[str, Any]]
    load_gradio: Callable[[], Any]
    progress_update: Callable[[Any, float, str], None]


class AssetService:
    """Keep file handling and Blender preparation out of the UI callback module."""

    def __init__(self, root: Path, runtime_dir: Path, dependencies: AssetDependencies):
        self.root = root
        self.runtime_dir = runtime_dir
        self.dependencies = dependencies

    def _blender(self, blender_text: str) -> str:
        blender = blender_text.strip() or self.dependencies.find_blender()
        if blender != "blender" and not Path(blender).exists():
            raise ValueError(f"Blender executable not found: {blender}")
        return blender

    @staticmethod
    def normalize_uploaded_path(file_value: Any) -> str | None:
        """Normalize Gradio 5/6 file values to one local filesystem path."""
        if file_value is None or file_value == "":
            return None
        if isinstance(file_value, (list, tuple)):
            if not file_value:
                return None
            if len(file_value) != 1:
                raise ValueError("Please choose one .blend, .fbx, or .obj file at a time.")
            return AssetService.normalize_uploaded_path(file_value[0])
        if isinstance(file_value, (str, Path)):
            return str(file_value)
        if isinstance(file_value, dict):
            for key in ("path", "tmp_path", "name"):
                value = file_value.get(key)
                if value:
                    return str(value)
            return None
        for attribute in ("path", "tmp_path", "name"):
            value = getattr(file_value, attribute, None)
            if value:
                return str(value)
        return None

    def _sample_update(self, row: dict[str, Any]):
        gr = self.dependencies.load_gradio()
        return gr.Dropdown(choices=[row["id"]], value=row["id"], label="Test asset")

    @staticmethod
    def _read_job_status(job_dir: Path) -> dict[str, Any]:
        status_path = job_dir / "job_status.json"
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"status": "unavailable", "task_id": job_dir.name, "status_path": str(status_path)}
        return payload if isinstance(payload, dict) else {"status": "invalid", "task_id": job_dir.name, "status_path": str(status_path)}

    def prepare_uploaded_asset(
        self,
        file_path: Any,
        blender_text: str,
        threshold_text: str,
        progress: Any,
    ) -> tuple[str, Any, dict[str, Any], str, str | None, str | None, str | None, str | None, str | None, str]:
        normalized_path = self.normalize_uploaded_path(file_path)
        if not normalized_path:
            raise ValueError("Please choose a .blend, .fbx, or .obj file first.")
        source = Path(normalized_path).expanduser().resolve()
        blender = self._blender(blender_text)
        threshold_path = self.dependencies.resolve_threshold_path(threshold_text)
        thresholds = self.dependencies.load_thresholds(threshold_path)
        job_dir = self.runtime_dir / f"job_{uuid.uuid4().hex[:10]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        self.dependencies.progress_update(progress, 0.05, "上传阶段")
        staged = stage_asset(source, job_dir, int(thresholds["max_upload_size_bytes"]))
        copied = staged.staged_path
        adaptive = self.dependencies.choose_adaptive_inspection_settings(copied, thresholds)
        runtime_threshold_path = job_dir / "inspection_thresholds.runtime.json"
        runtime_thresholds = dict(thresholds)
        runtime_thresholds.update({key: adaptive[key] for key in ("preview_views", "preview_resolution", "max_diagnostic_triangles")})
        runtime_thresholds["runtime_inspection_strategy"] = adaptive["strategy"]
        runtime_threshold_path.write_text(json.dumps(runtime_thresholds, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            blender, "-b", "-P", str(self.root / "blender" / "inspect_asset.py"), "--",
            "--input", str(copied), "--out", str(job_dir), "--views", str(adaptive["preview_views"]),
            "--resolution", str(adaptive["preview_resolution"]), "--config", str(runtime_threshold_path),
        ]
        log_path = self.dependencies.run_blender_job(command, job_dir, progress, timeout=int(thresholds["job_timeout_seconds"]))
        manifest = job_dir / "manifest.jsonl"
        if not manifest.exists():
            raise RuntimeError("Blender finished without producing a runtime manifest.")
        self.dependencies.write_runtime_inspection_metadata(manifest, adaptive, staged.to_dict())
        rows, _ = self.dependencies.load_rows(manifest)
        row = rows[0]
        paths = self.dependencies.resolve_image_paths(row, manifest)
        artifact_failures = validate_runtime_artifacts(row, paths)
        if artifact_failures:
            details = "; ".join(f"{item['artifact']}: {item['reason']}" for item in artifact_failures)
            raise RuntimeError(
                "Blender finished, but required inspection outputs are incomplete. "
                f"Review the job log at {log_path}. Details: {details}"
            )
        info = {
            "source_file": source.name,
            "runtime_job": str(job_dir),
            "task_id": job_dir.name,
            "log_file": str(log_path),
            "job_status_file": str(job_dir / "job_status.json"),
            "job_status": self._read_job_status(job_dir),
            "adaptive_inspection": adaptive,
            "staging": staged.to_dict(),
            "metadata": compact_metadata(row["metadata"]),
            "issue_locator_file": paths.get("issue_locator"),
            "issue_selection_script_file": paths.get("issue_selection_script"),
            "artifact_validation": {"status": "passed", "failures": []},
        }
        return (
            str(manifest), self._sample_update(row), info, paths["views"], paths["uv"] or None,
            paths["uv_heatmap"] or None, paths["normal"] or None, paths["model"] or None,
            paths["model_overlay"] or None,
            f"Prepared successfully: {source.name} | task: {job_dir.name} | strategy: {adaptive['strategy']} ({adaptive['preview_views']} views / {adaptive['preview_resolution']}px) | log: {log_path} | status: {job_dir / 'job_status.json'}",
        )

    def repair_and_reinspect(
        self,
        manifest_text: str,
        blender_text: str,
        threshold_text: str,
        progress: Any,
    ) -> tuple[str, Any, dict[str, Any], str, str | None, str | None, str | None, str | None, str | None, str]:
        if not manifest_text:
            raise ValueError("Prepare or upload an asset before requesting repair.")
        manifest = Path(manifest_text).expanduser().resolve()
        if not manifest.exists():
            raise ValueError(f"Runtime manifest not found: {manifest}")
        source_candidates = sorted(
            (path for path in manifest.parent.iterdir() if path.suffix.lower() in {".blend", ".fbx", ".obj"}),
            key=lambda path: path.name.lower(),
        )
        if not source_candidates:
            raise ValueError("The runtime job no longer contains the original .blend/.fbx/.obj copy.")
        source = source_candidates[0]
        blender = self._blender(blender_text)
        threshold_path = self.dependencies.resolve_threshold_path(threshold_text)
        thresholds = self.dependencies.load_thresholds(threshold_path)
        job_dir = self.runtime_dir / f"repair_{uuid.uuid4().hex[:10]}"
        job_dir.mkdir(parents=True, exist_ok=True)
        repaired_output = job_dir / "repaired_asset.blend"
        adaptive = self.dependencies.choose_adaptive_inspection_settings(source, thresholds)
        runtime_threshold_path = job_dir / "inspection_thresholds.runtime.json"
        runtime_thresholds = dict(thresholds)
        runtime_thresholds.update({key: adaptive[key] for key in ("preview_views", "preview_resolution", "max_diagnostic_triangles")})
        runtime_thresholds["runtime_inspection_strategy"] = adaptive["strategy"]
        runtime_threshold_path.write_text(json.dumps(runtime_thresholds, ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            blender, "-b", "-P", str(self.root / "blender" / "inspect_asset.py"), "--",
            "--input", str(source), "--out", str(job_dir), "--views", str(adaptive["preview_views"]),
            "--resolution", str(adaptive["preview_resolution"]), "--repair", "--repaired-output",
            str(repaired_output), "--config", str(runtime_threshold_path),
        ]
        log_path = self.dependencies.run_blender_job(command, job_dir, progress, timeout=max(300, int(thresholds["job_timeout_seconds"])))
        repaired_manifest = job_dir / "manifest.jsonl"
        if not repaired_manifest.exists():
            raise RuntimeError("Repair completed without producing a new runtime manifest.")
        staging = None
        staging_path = manifest.parent / "staging.json"
        if staging_path.exists():
            try:
                staging = json.loads(staging_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                staging = {"warnings": ["Unable to read original staging metadata."]}
        self.dependencies.write_runtime_inspection_metadata(repaired_manifest, adaptive, staging)
        rows, _ = self.dependencies.load_rows(repaired_manifest)
        row = rows[0]
        paths = self.dependencies.resolve_image_paths(row, repaired_manifest)
        artifact_failures = validate_runtime_artifacts(row, paths)
        if artifact_failures:
            details = "; ".join(f"{item['artifact']}: {item['reason']}" for item in artifact_failures)
            raise RuntimeError(
                "Repair finished, but required inspection outputs are incomplete. "
                f"Review the job log at {log_path}. Details: {details}"
            )
        info = {
            "source_file": source.name,
            "runtime_job": str(job_dir),
            "task_id": job_dir.name,
            "repaired_output": str(repaired_output),
            "log_file": str(log_path),
            "job_status_file": str(job_dir / "job_status.json"),
            "job_status": self._read_job_status(job_dir),
            "repair_applied": True,
            "adaptive_inspection": adaptive,
            "staging": staging,
            "metadata": compact_metadata(row["metadata"]),
            "issue_locator_file": paths.get("issue_locator"),
            "issue_selection_script_file": paths.get("issue_selection_script"),
            "artifact_validation": {"status": "passed", "failures": []},
        }
        return (
            str(repaired_manifest), self._sample_update(row), info, paths["views"], paths["uv"] or None,
            paths["uv_heatmap"] or None, paths["normal"] or None, paths["model"] or None,
            paths["model_overlay"] or None,
            f"Repaired a runtime copy and re-inspected: {source.name} | task: {job_dir.name} | strategy: {adaptive['strategy']} ({adaptive['preview_views']} views / {adaptive['preview_resolution']}px) | log: {log_path} | status: {job_dir / 'job_status.json'}",
        )
