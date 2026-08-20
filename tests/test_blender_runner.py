import json
import sys
import tempfile
import unittest
from pathlib import Path

from src.blender_runner import BlenderJobRunner
from src.inspection_enums import JobStatus


class BlenderRunnerTests(unittest.TestCase):
    def test_runner_writes_completed_status_and_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir) / "job"
            runner = BlenderJobRunner(Path(temp_dir))
            log_path = runner.run(
                [sys.executable, "-c", "print('manifest generated')"],
                job_dir,
                timeout=10,
            )
            status = json.loads((job_dir / "job_status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], JobStatus.COMPLETED.value)
            self.assertEqual(status["return_code"], 0)
            self.assertEqual(status["task_id"], "job")
            self.assertEqual(status["progress"], 1.0)
            self.assertEqual(BlenderJobRunner.read_status(job_dir)["status"], JobStatus.COMPLETED.value)
            self.assertTrue(log_path.exists())
            self.assertIn("manifest generated", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
