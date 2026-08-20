import unittest

from demo.app import render_provenance_summary


class TraceabilityUiTests(unittest.TestCase):
    def test_provenance_summary_is_collapsed_and_exposes_reproducibility_fields(self):
        html = render_provenance_summary(
            {
                "provenance": {
                    "task_id": "job_123",
                    "detected_at_utc": "2026-08-19T10:00:00+00:00",
                    "detector_version": "inspector-test",
                    "input_sha256": "a" * 64,
                    "effective_threshold_config_sha256": "b" * 64,
                    "scoring_config_sha256": "c" * 64,
                    "staging_warnings": ["missing optional sidecar"],
                }
            },
            "中文",
        )

        self.assertIn("<details>", html)
        self.assertIn("任务 ID", html)
        self.assertIn("job_123", html)
        self.assertIn("输入文件 SHA-256", html)
        self.assertIn("aaaaaaaaaaaaaaaa…", html)
        self.assertIn("暂存警告", html)
        self.assertNotIn("a" * 64, html)

    def test_missing_provenance_does_not_add_empty_panel(self):
        self.assertEqual(render_provenance_summary({}, "English"), "")


if __name__ == "__main__":
    unittest.main()
