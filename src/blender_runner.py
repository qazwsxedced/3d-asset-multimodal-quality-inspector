"""Cross-platform Blender subprocess runner for the inspection service."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable

from src.inspection_enums import JobStatus


ProgressCallback = Callable[[float, str], None] | None


class BlenderJobRunner:
    """Run Blender jobs with logs, progress, cancellation, and status records."""

    def __init__(self, root: Path):
        self.root = root
        self.active_processes: dict[str, subprocess.Popen[str]] = {}
        self.cancel_requested: set[str] = set()

    @staticmethod
    def _progress(progress: ProgressCallback, value: float, description: str) -> None:
        if callable(progress):
            progress(value, desc=description)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        """Terminate the Blender process and its children on every supported OS."""
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                process.terminate()

    @staticmethod
    def _write_status(status_path: Path, status: dict[str, Any]) -> None:
        """Write status atomically so polling never observes partial JSON."""
        status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = status_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(status_path)

    @staticmethod
    def read_status(job_dir: Path) -> dict[str, Any]:
        """Read a persisted task status for polling or post-failure recovery."""
        status_path = Path(job_dir) / "job_status.json"
        if not status_path.exists():
            return {"status": "not_found", "task_id": Path(job_dir).name, "status_path": str(status_path)}
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "invalid", "task_id": Path(job_dir).name, "status_path": str(status_path), "error": str(exc)}
        return payload if isinstance(payload, dict) else {"status": "invalid", "task_id": Path(job_dir).name, "status_path": str(status_path)}

    def cancel(self) -> str:
        cancelled = 0
        for job_dir, process in list(self.active_processes.items()):
            if process.poll() is None:
                self.cancel_requested.add(job_dir)
                self._terminate(process)
                cancelled += 1
        return f"Cancellation requested for {cancelled} active job(s)."

    def run(self, command: list[str], job_dir: Path, progress: ProgressCallback = None, timeout: int = 240) -> Path:
        """Run Blender and persist a machine-readable job status record."""
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "blender.log"
        status_path = job_dir / "job_status.json"
        task_id = job_dir.name
        status: dict[str, Any] = {
            "task_id": task_id,
            "status": JobStatus.QUEUED.value,
            "progress": 0.0,
            "stage": "queued",
            "command": command,
            "timeout_seconds": timeout,
            "log_file": str(log_path),
            "status_path": str(status_path),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self._write_status(status_path, status)
        output_queue: Queue[str | None] = Queue()
        popen_kwargs: dict[str, Any] = {
            "cwd": str(self.root),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "bufsize": 1,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as exc:
            status.update({"status": JobStatus.FAILED.value, "error": str(exc), "return_code": None})
            status["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            self._write_status(status_path, status)
            raise RuntimeError(f"Unable to start Blender job {task_id}: {exc}. Status: {status_path}") from exc
        job_key = str(job_dir)
        self.active_processes[job_key] = process
        status.update({"status": JobStatus.PREPARING.value, "pid": process.pid})
        status["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        self._write_status(status_path, status)
        started = time.monotonic()

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                output_queue.put(line)
            output_queue.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        lines: list[str] = []
        last_line = ""
        timed_out = False
        descriptions = [
            ("OBJ/FBX/Blend 导入阶段", 0.22),
            ("几何、材质和动画统计阶段", 0.52),
            ("多视图和诊断图渲染阶段", 0.78),
            ("运行时报告整理阶段", 0.92),
        ]
        current_stage = descriptions[0][0]
        current_progress = 0.16

        def publish(value: float, description: str) -> None:
            nonlocal current_progress, current_stage
            current_progress = value
            current_stage = description
            stage_status = (
                JobStatus.IMPORTING.value if "导入" in description else
                JobStatus.INSPECTING.value if "统计" in description else
                JobStatus.RENDERING.value if "渲染" in description else
                JobStatus.GENERATING_REPORT.value if "整理" in description else
                JobStatus.PREPARING.value
            )
            status.update({"status": stage_status, "progress": value, "stage": description, "last_output": last_line})
            status["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            self._write_status(status_path, status)
            self._progress(progress, value, description)

        publish(current_progress, current_stage)
        finished = False
        while not finished:
            try:
                line = output_queue.get(timeout=0.2)
                if line is None:
                    finished = True
                    continue
                lines.append(line)
                last_line = line.strip()
                lowered = line.lower()
                if "obj import" in lowered or "fbx" in lowered or "read blend" in lowered:
                    publish(descriptions[0][1], descriptions[0][0])
                elif "inspect_asset.py" in lowered or "statistics" in lowered or "stats" in lowered or "analy" in lowered:
                    publish(descriptions[1][1], descriptions[1][0])
                elif "starting gltf" in lowered or "render" in lowered or "saved:" in lowered:
                    publish(descriptions[2][1], descriptions[2][0])
                elif "manifest" in lowered or "report" in lowered:
                    publish(descriptions[3][1], descriptions[3][0])
            except Empty:
                if process.poll() is not None and not reader.is_alive():
                    finished = True
            if time.monotonic() - started > timeout:
                timed_out = True
                self._terminate(process)
                lines.append(f"Timed out after {timeout}s during {current_stage}\n")
                break

        reader.join(timeout=2)
        try:
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._terminate(process)
            return_code = process.wait(timeout=10)
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        cancelled = job_key in self.cancel_requested
        self.cancel_requested.discard(job_key)
        self.active_processes.pop(job_key, None)
        elapsed = round(time.monotonic() - started, 1)
        log_text = "".join(lines)
        log_path.write_text(log_text, encoding="utf-8", errors="replace")
        status_value = (
            JobStatus.CANCELLED.value
            if cancelled
            else JobStatus.TIMEOUT.value
            if timed_out
            else JobStatus.COMPLETED.value
            if return_code == 0
            else JobStatus.FAILED.value
        )
        status = {
            "task_id": task_id,
            "status": status_value,
            "command": command,
            "return_code": return_code,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "timeout_seconds": timeout,
            "elapsed_seconds": elapsed,
            "last_stage": current_stage,
            "progress": 1.0 if status_value == JobStatus.COMPLETED.value else current_progress,
            "last_output": last_line,
            "log_file": str(log_path),
            "status_path": str(status_path),
            "pid": process.pid,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self._write_status(status_path, status)
        if cancelled:
            raise RuntimeError(f"Blender job cancelled during {current_stage}. Log: {log_path}")
        if timed_out:
            stage_suggestions = {
                descriptions[0][0]: "检查文件是否过大、是否包含复杂外部链接或损坏的 FBX/Blend 数据；必要时先用轻量导出验证。",
                descriptions[1][0]: "降低诊断三角形上限、暂时关闭复杂动画/组件分析，或延长 job_timeout_seconds。",
                descriptions[2][0]: "减少 preview_views 和 preview_resolution，先完成规则统计，再单独生成高分辨率预览。",
                descriptions[3][0]: "检查磁盘空间、runtime_uploads 目录权限和 Blender 日志中的报告写入错误。",
            }
            suggestion = stage_suggestions.get(current_stage, "查看 Blender 日志尾部，并根据当前阶段调整检测配置。")
            tail = log_text[-5000:]
            raise RuntimeError(
                f"Blender job timed out after {elapsed}s during {current_stage}. "
                f"Log: {log_path}\nStatus: {status_path}\n"
                f"建议 / Suggested action: {suggestion}\n{tail}"
            )
        if return_code != 0:
            tail = log_text[-5000:]
            raise RuntimeError(f"Blender job failed (exit={return_code}) during {current_stage}. Log: {log_path}\nStatus: {status_path}\n{tail}")
        self._progress(progress, 1.0, "检测任务完成")
        return log_path
