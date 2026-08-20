import json
import tempfile
import unittest
from pathlib import Path

from src.provenance import build_provenance
from src.report_service import write_html_report, write_json_audit


class ProvenanceReportTests(unittest.TestCase):
    def test_runtime_threshold_and_input_hash_are_recorded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "job_123"
            task_dir.mkdir()
            manifest = task_dir / "manifest.jsonl"
            manifest.write_text("{}\n", encoding="utf-8")
            configured = root / "inspection_thresholds.json"
            configured.write_text('{"max_faces": 50000}\n', encoding="utf-8")
            runtime = task_dir / "inspection_thresholds.runtime.json"
            runtime.write_text('{"max_faces": 1000}\n', encoding="utf-8")

            provenance = build_provenance(
                manifest,
                configured,
                {
                    "asset_staging": {
                        "source_file": "model.obj",
                        "source_sha256": "abc123",
                        "source_size_bytes": 42,
                        "warnings": ["missing texture"],
                    }
                },
                "Rule baseline",
                "B4",
            )

            self.assertEqual(provenance["task_id"], "job_123")
            self.assertEqual(provenance["input_sha256"], "abc123")
            self.assertEqual(provenance["effective_threshold_config_path"], str(runtime.resolve()))
            self.assertEqual(len(provenance["effective_threshold_config_sha256"]), 64)
            self.assertEqual(len(provenance["scoring_config_sha256"]), 64)

    def test_html_report_contains_provenance_and_structured_audit_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = {
                "sample_id": "sample_000001",
                "asset_id": "asset_00001",
                "mode": "Rule baseline",
                "condition": "B4",
                "feedback_language": "中文",
                "release_decision": {"code": "publish", "label": "可发布"},
                "agreement_score": 1.0,
                "review_required": False,
                "disagreement_reasons": [],
                "provenance": {
                    "task_id": "job_456",
                    "input_sha256": "deadbeef",
                    "detector_version": "test-detector",
                },
                "selected_result": {"issues": [], "health_score": {"score": 100}},
                "metadata": {"triangle_count": 12},
                "selected_source": "rules",
                "artifacts": {
                    "issue_locator": str(root / "issue_locator.json"),
                    "issue_selection_script": str(root / "apply_issue_locator.py"),
                },
            }
            (root / "issue_locator.json").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
            (root / "apply_issue_locator.py").write_text("print('select faces')\n", encoding="utf-8")
            report = write_html_report(
                result,
                {
                    "issue_locator": str(root / "issue_locator.json"),
                    "issue_selection_script": str(root / "apply_issue_locator.py"),
                },
                "<p>可发布</p>",
                "<p>无问题</p>",
                "",
                root,
            )

            report_text = Path(report).read_text(encoding="utf-8")
            self.assertIn("job_456", report_text)
            self.assertIn("deadbeef", report_text)
            self.assertIn("Structured audit data", report_text)
            self.assertIn("triangle_count", report_text)
            self.assertIn("issue_locator.json", report_text)
            self.assertIn("apply_issue_locator.py", report_text)
            self.assertTrue(Path(report).name.startswith("sample_000001_job_456_"))

            audit_path = write_json_audit(result, root)
            audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
            self.assertEqual(audit["audit_schema_version"], "1.0")
            self.assertEqual(audit["condition"], "B4")
            self.assertEqual(audit["score"]["release_decision"]["code"], "publish")
            self.assertEqual(audit["provenance"]["input_sha256"], "deadbeef")
            self.assertEqual(audit["metadata"]["triangle_count"], 12)
            self.assertEqual(audit["asset"]["asset_id"], "asset_00001")
            self.assertEqual(audit["geometry"]["metrics"]["triangle_count"], 12)
            self.assertEqual(audit["artifacts"]["issue_locator"], str(root / "issue_locator.json"))
            self.assertEqual(audit["artifacts"]["issue_selection_script"], str(root / "apply_issue_locator.py"))
            self.assertTrue(Path(audit_path).name.endswith(".json"))


if __name__ == "__main__":
    unittest.main()
