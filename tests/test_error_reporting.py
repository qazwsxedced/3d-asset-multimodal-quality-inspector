import json
import tempfile
import unittest
from pathlib import Path

from src.error_reporting import format_failure_message, write_failure_log


class ErrorReportingTests(unittest.TestCase):
    def test_timeout_message_contains_action_and_log(self):
        message = format_failure_message(RuntimeError("Blender job timed out after 10s"), Path("job.log"))
        self.assertIn("检测超时", message)
        self.assertIn("降低预览分辨率", message)
        self.assertIn("job.log", message)

    def test_failure_log_is_structured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "inspection.log"
            try:
                raise ValueError("bad fixture")
            except ValueError as error:
                write_failure_log(path, "inspection", error)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["operation"], "inspection")
            self.assertEqual(payload["error_type"], "ValueError")
            self.assertIn("bad fixture", payload["traceback"])


if __name__ == "__main__":
    unittest.main()
