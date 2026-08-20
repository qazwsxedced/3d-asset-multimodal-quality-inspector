import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_inspection_test_suite import check_artifact_contract
from src.issue_locator_script import write_blender_selection_script


class InspectionSuiteArtifactTests(unittest.TestCase):
    def test_valid_locator_artifacts_pass_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = {"schema_version": "1.1", "source_issue_breakdown": []}
            (root / "issue_locator.json").write_text(json.dumps(payload), encoding="utf-8")
            write_blender_selection_script(payload, root / "apply_issue_locator.py")
            failures = check_artifact_contract({"artifacts": {
                "issue_locator": "issue_locator.json",
                "issue_selection_script": "apply_issue_locator.py",
            }}, root)
            self.assertEqual(failures, [])

    def test_missing_artifact_fails_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            failures = check_artifact_contract({"artifacts": {}}, Path(temp_dir))
            self.assertEqual({failure["artifact"] for failure in failures}, {"issue_locator", "issue_selection_script"})


if __name__ == "__main__":
    unittest.main()
