"""Small persistent background queue for long-running local inspections.

This is intentionally process-local execution with filesystem-backed state. It
removes the Blender wait from the Gradio request, while keeping every queued
task and result discoverable after a page refresh. A future multi-process
deployment can replace the executor without changing the task record format.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.inspection_enums import JobStatus


Worker = Callable[[Path, Callable[[float, str], None]], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskQueue:
    """Submit local jobs and persist queue state/results under one runtime root."""

    def __init__(self, root: Path, max_workers: int = 1):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="asset-inspection")
        self._futures: dict[str, Future[Any]] = {}
        self._lock = threading.RLock()
        self._recover_orphaned_tasks()

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "invalid", "error": str(exc), "status_path": str(path)}
        return payload if isinstance(payload, dict) else {"status": "invalid", "status_path": str(path)}

    def _status_path(self, task_id: str) -> Path:
        return self.root / task_id / "queue_status.json"

    def _recover_orphaned_tasks(self) -> None:
        """Do not claim unfinished work resumed when the process was restarted."""
        for status_path in self.root.glob("queue_*/queue_status.json"):
            record = self._read_json(status_path)
            if record.get("status") not in {JobStatus.QUEUED.value, JobStatus.PREPARING.value}:
                continue
            record.update({
                "status": JobStatus.FAILED.value,
                "failure_code": "process_restarted",
                "retryable": True,
                "error": "The queue process restarted before this task completed; submit it again.",
                "updated_at_utc": _now(),
            })
            self._write_json(status_path, record)

    def submit(self, kind: str, payload: dict[str, Any], worker: Worker) -> dict[str, Any]:
        """Queue a worker and return its ID immediately."""
        task_id = f"queue_{uuid.uuid4().hex[:12]}"
        task_dir = self.root / task_id
        status_path = task_dir / "queue_status.json"
        result_path = task_dir / "result.json"
        record = {
            "task_id": task_id,
            "kind": str(kind),
            "status": JobStatus.QUEUED.value,
            "progress": 0.0,
            "stage": "queued",
            "payload": payload,
            "status_path": str(status_path),
            "result_path": str(result_path),
            "submitted_at_utc": _now(),
            "updated_at_utc": _now(),
        }
        self._write_json(status_path, record)
        future = self._executor.submit(self._run, task_id, task_dir, worker)
        with self._lock:
            self._futures[task_id] = future
        return record

    def _run(self, task_id: str, task_dir: Path, worker: Worker) -> None:
        status_path = task_dir / "queue_status.json"
        result_path = task_dir / "result.json"
        record = self._read_json(status_path)

        def update(progress: float, stage: str) -> None:
            record.update({
                "status": JobStatus.PREPARING.value,
                "progress": max(0.0, min(1.0, float(progress))),
                "stage": str(stage),
                "updated_at_utc": _now(),
            })
            self._write_json(status_path, record)

        try:
            update(0.01, "后台任务已启动")
            result = worker(task_dir, update)
            if not isinstance(result, dict):
                raise TypeError("background worker must return a JSON object")
            self._write_json(result_path, result)
            record.update({
                "status": JobStatus.COMPLETED.value,
                "progress": 1.0,
                "stage": "任务完成",
                "result_path": str(result_path),
                "updated_at_utc": _now(),
            })
        except Exception as exc:  # noqa: BLE001 - persisted for operator inspection
            record.update({
                "status": JobStatus.FAILED.value,
                "progress": record.get("progress", 0.0),
                "error": str(exc),
                "failure_type": type(exc).__name__,
                "retryable": True,
                "updated_at_utc": _now(),
            })
        finally:
            self._write_json(status_path, record)
            with self._lock:
                self._futures.pop(task_id, None)

    def get(self, task_id: str | None) -> dict[str, Any]:
        candidate = str(task_id or "").strip()
        if not candidate or candidate in {".", ".."} or "/" in candidate or "\\" in candidate:
            return {"task_id": candidate, "status": "not_found"}
        status_path = self._status_path(candidate)
        if not status_path.exists():
            return {"task_id": candidate, "status": "not_found"}
        record = self._read_json(status_path)
        result_path = Path(str(record.get("result_path", status_path.parent / "result.json")))
        if record.get("status") == JobStatus.COMPLETED.value and result_path.exists():
            record["result_available"] = True
        record["retryable"] = bool(record.get("retryable", record.get("status") in {JobStatus.FAILED.value, JobStatus.TIMEOUT.value, JobStatus.CANCELLED.value}))
        return record

    def read_result(self, task_id: str | None) -> dict[str, Any] | None:
        record = self.get(task_id)
        if record.get("status") != JobStatus.COMPLETED.value:
            return None
        result_path = Path(str(record.get("result_path", "")))
        if not result_path.exists():
            return None
        payload = self._read_json(result_path)
        return payload if payload.get("status", "ok") != "invalid" else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        records = [self._read_json(path) for path in self.root.glob("queue_*/queue_status.json")]
        records.sort(key=lambda item: str(item.get("updated_at_utc", "")), reverse=True)
        return records[: int(limit)]

    def cancel(self, task_id: str | None) -> dict[str, Any]:
        """Cancel only work that has not started; running Blender uses the existing cancel action."""
        record = self.get(task_id)
        if record.get("status") != JobStatus.QUEUED.value:
            return {**record, "cancelled": False, "cancel_reason": "Only queued tasks can be cancelled here."}
        future = self._futures.get(str(task_id))
        if not future or not future.cancel():
            return {**record, "cancelled": False, "cancel_reason": "The worker has already started."}
        status_path = self._status_path(str(task_id))
        record.update({"status": JobStatus.CANCELLED.value, "cancelled": True, "updated_at_utc": _now()})
        self._write_json(status_path, record)
        return record

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)
