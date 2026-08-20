"""Persistent task lookup and retention helpers for runtime inspection jobs.

The Blender runner writes one ``job_status.json`` file per job directory.  This
module deliberately keeps the lookup layer independent from Gradio and from a
database so the same records can be queried by the web UI, scripts, or a future
background worker.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from src.inspection_enums import JobStatus


TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.TIMEOUT.value,
}
RETRYABLE_STATUSES = {
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.TIMEOUT.value,
}


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a persisted ISO timestamp, returning an aware UTC value."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStore:
    """Discover and query persisted task records below one runtime root.

    ``job_status.json`` is the source of truth.  There is intentionally no
    in-memory-only index: a process restart must not make a completed task
    disappear from the task history.
    """

    def __init__(self, root: Path, retention_seconds: int = 7 * 24 * 60 * 60):
        self.root = Path(root).expanduser().resolve()
        if retention_seconds < 0:
            raise ValueError("retention_seconds must be non-negative")
        self.retention_seconds = int(retention_seconds)

    def _status_paths(self) -> Iterable[Path]:
        if not self.root.exists() or not self.root.is_dir():
            return ()
        return (
            path
            for pattern in ("job_status.json", "queue_status.json")
            for path in self.root.rglob(pattern)
            if path.is_file()
        )

    @staticmethod
    def _read_status(status_path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "task_id": status_path.parent.name,
                "status": "invalid",
                "status_path": str(status_path),
                "error": str(exc),
            }
        if not isinstance(payload, dict):
            return {
                "task_id": status_path.parent.name,
                "status": "invalid",
                "status_path": str(status_path),
                "error": "status record must be a JSON object",
            }
        record = dict(payload)
        record.setdefault("task_id", status_path.parent.name)
        record.setdefault("status_path", str(status_path))
        record.setdefault("job_dir", str(status_path.parent))
        return record

    def _records(self) -> list[dict[str, Any]]:
        records = [self._read_status(path) for path in self._status_paths()]
        records.sort(
            key=lambda item: _parse_timestamp(item.get("updated_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return records

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return newest task records first, bounded for safe UI rendering."""
        if limit < 1:
            return []
        return self._records()[: int(limit)]

    def get(self, task_id: str | None) -> dict[str, Any]:
        """Return one task record without accepting arbitrary filesystem paths."""
        candidate = str(task_id or "").strip()
        if not candidate or candidate in {".", ".."} or "/" in candidate or "\\" in candidate:
            return {"task_id": candidate, "status": "not_found"}
        for record in self._records():
            if str(record.get("task_id", "")) == candidate or Path(str(record.get("job_dir", ""))).name == candidate:
                return record
        return {"task_id": candidate, "status": "not_found"}

    @staticmethod
    def is_retryable(record_or_status: dict[str, Any] | str | None) -> bool:
        """Whether a terminal task can be offered a retry action."""
        status = (
            record_or_status.get("status")
            if isinstance(record_or_status, dict)
            else record_or_status
        )
        return str(status or "") in RETRYABLE_STATUSES

    @classmethod
    def retry_decision(cls, record: dict[str, Any]) -> dict[str, Any]:
        status = str(record.get("status", ""))
        retryable = cls.is_retryable(record)
        if retryable:
            reason = {
                JobStatus.FAILED.value: "任务失败，可以重新执行同一输入。",
                JobStatus.CANCELLED.value: "任务被取消，可以重新执行同一输入。",
                JobStatus.TIMEOUT.value: "任务超时，建议降低预览/诊断负载或延长超时后重试。",
            }.get(status, "任务可以重试。")
        elif status == JobStatus.COMPLETED.value:
            reason = "任务已完成，无需重试。"
        elif status in {JobStatus.QUEUED.value, JobStatus.PREPARING.value, JobStatus.IMPORTING.value, JobStatus.INSPECTING.value, JobStatus.RENDERING.value, JobStatus.GENERATING_REPORT.value}:
            reason = "任务仍在运行，暂不建议重复提交。"
        else:
            reason = "任务状态不可用，请先查看状态记录。"
        return {"task_id": record.get("task_id"), "status": status, "retryable": retryable, "reason": reason}

    def cleanup_expired(self, now: datetime | None = None, dry_run: bool = True) -> list[dict[str, Any]]:
        """Find or explicitly remove old terminal task directories.

        The default is a dry run.  Deletion is only allowed for a terminal job
        directory that resolves beneath ``root``; active or malformed jobs are
        never removed.  The web UI uses the dry-run mode so retention policy can
        be inspected without silently deleting evidence.
        """
        current = (now or _utc_now()).astimezone(timezone.utc)
        cutoff = current - timedelta(seconds=self.retention_seconds)
        expired: list[dict[str, Any]] = []
        for record in self._records():
            if str(record.get("status", "")) not in TERMINAL_STATUSES:
                continue
            timestamp = _parse_timestamp(record.get("updated_at_utc"))
            job_dir_text = record.get("job_dir") or Path(str(record.get("status_path", ""))).parent
            job_dir = Path(str(job_dir_text)).expanduser().resolve()
            try:
                job_dir.relative_to(self.root)
            except ValueError:
                continue
            if timestamp is None or timestamp >= cutoff or not job_dir.is_dir():
                continue
            item = {
                "task_id": record.get("task_id", job_dir.name),
                "status": record.get("status"),
                "job_dir": str(job_dir),
                "updated_at_utc": record.get("updated_at_utc"),
                "dry_run": dry_run,
            }
            if not dry_run:
                shutil.rmtree(job_dir)
                item["deleted"] = True
            else:
                item["deleted"] = False
            expired.append(item)
        return expired
