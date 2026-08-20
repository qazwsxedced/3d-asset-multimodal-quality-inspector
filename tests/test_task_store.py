import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def _write_status(self, root: Path, name: str, status: str, updated_at: datetime):
        job_dir = root / name
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job_status.json").write_text(
            json.dumps(
                {
                    "task_id": name,
                    "status": status,
                    "updated_at_utc": updated_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        return job_dir

    def test_get_list_and_retry_decision_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            self._write_status(root, "job_failed", "failed", now)
            self._write_status(root, "job_done", "completed", now - timedelta(seconds=1))
            store = TaskStore(root)

            failed = store.get("job_failed")
            self.assertEqual(failed["status"], "failed")
            self.assertTrue(store.is_retryable(failed))
            self.assertTrue(store.retry_decision(failed)["retryable"])
            self.assertEqual(store.get("../job_failed")["status"], "not_found")
            self.assertEqual([item["task_id"] for item in store.list()], ["job_failed", "job_done"])

    def test_cleanup_defaults_to_dry_run_and_only_targets_old_terminal_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = datetime.now(timezone.utc) - timedelta(days=10)
            old_dir = self._write_status(root, "job_old", "failed", old)
            active_dir = self._write_status(root, "job_active", "inspecting", old)
            store = TaskStore(root, retention_seconds=60)

            candidates = store.cleanup_expired()
            self.assertEqual([item["task_id"] for item in candidates], ["job_old"])
            self.assertTrue(old_dir.exists())
            self.assertTrue(active_dir.exists())

            deleted = store.cleanup_expired(dry_run=False)
            self.assertEqual(deleted[0]["deleted"], True)
            self.assertFalse(old_dir.exists())
            self.assertTrue(active_dir.exists())


if __name__ == "__main__":
    unittest.main()
