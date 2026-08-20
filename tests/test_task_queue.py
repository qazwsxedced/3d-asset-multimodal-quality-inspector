import json
import tempfile
import time
import unittest
from pathlib import Path

from src.task_queue import TaskQueue


class TaskQueueTests(unittest.TestCase):
    @staticmethod
    def _wait(queue: TaskQueue, task_id: str, timeout: float = 3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = queue.get(task_id)
            if record.get("status") in {"completed", "failed", "cancelled"}:
                return record
            time.sleep(0.02)
        raise AssertionError(f"task did not finish: {task_id}")

    def test_submit_persists_result_and_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = TaskQueue(Path(directory), max_workers=1)
            record = queue.submit(
                "fixture",
                {"source": "unit-test"},
                lambda _task_dir, update: (update(0.5, "testing"), {"answer": 42})[1],
            )
            completed = self._wait(queue, record["task_id"])
            self.assertEqual(completed["status"], "completed")
            self.assertTrue(completed["result_available"])
            self.assertEqual(queue.read_result(record["task_id"])["answer"], 42)
            self.assertEqual(queue.list()[0]["task_id"], record["task_id"])
            queue.shutdown()

    def test_worker_failure_is_persisted_as_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = TaskQueue(Path(directory))

            def fail(_task_dir, _update):
                raise RuntimeError("fixture failure")

            record = queue.submit("fixture", {}, fail)
            failed = self._wait(queue, record["task_id"])
            self.assertEqual(failed["status"], "failed")
            self.assertTrue(failed["retryable"])
            self.assertIn("fixture failure", failed["error"])
            queue.shutdown()

    def test_restart_marks_unfinished_queue_task_as_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dir = root / "queue_orphan"
            task_dir.mkdir()
            status_path = task_dir / "queue_status.json"
            status_path.write_text(
                json.dumps({"task_id": "queue_orphan", "status": "preparing"}),
                encoding="utf-8",
            )
            queue = TaskQueue(root)
            record = queue.get("queue_orphan")
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["failure_code"], "process_restarted")
            self.assertTrue(record["retryable"])
            queue.shutdown()


if __name__ == "__main__":
    unittest.main()
