import unittest
from dataclasses import replace

from src.inspection_result import InspectionResult, RESULT_SCHEMA_VERSION


class InspectionResultTests(unittest.TestCase):
    def test_legacy_result_is_mapped_to_typed_sections(self):
        model = InspectionResult.from_legacy(
            {
                "asset_id": "asset_1",
                "sample_id": "sample_1",
                "mode": "Rule baseline",
                "condition": "B4",
                "selected_source": "rule_baseline",
                "metadata": {
                    "triangle_count": 120,
                    "uv_overlap_ratio": 0.02,
                    "material_count": 2,
                    "loading_risk": "medium",
                    "asset_staging": {"source_file": "model.obj"},
                },
                "selected_result": {
                    "issues": [{"issue_id": "defect:uv_overlap"}],
                    "health_score": {"score": 72},
                    "inspection_coverage": {
                        "geometry": "checked",
                        "uv": "sampled",
                        "materials": "checked",
                        "animation": "not_applicable",
                        "runtime": "checked",
                    },
                },
                "provenance": {"task_id": "job_1"},
                "artifacts": {"issue_locator": "issue_locator.json"},
            }
        )

        self.assertEqual(model.schema_version, RESULT_SCHEMA_VERSION)
        self.assertEqual(model.asset.source_format, "obj")
        self.assertEqual(model.geometry.metrics["triangle_count"], 120)
        self.assertEqual(model.uv.coverage, "sampled")
        self.assertEqual(model.materials.metrics["material_count"], 2)
        self.assertEqual(model.runtime.metrics["loading_risk"], "medium")
        self.assertEqual(model.score.health["score"], 72)
        self.assertEqual(model.to_dict()["provenance"]["task_id"], "job_1")
        self.assertEqual(model.to_dict()["artifacts"]["issue_locator"], "issue_locator.json")
        self.assertEqual(model.issues[0]["schema_version"], "1.0")
        self.assertIn("current_value", model.issues[0])
        self.assertEqual(model.validate(), [])

    def test_sampled_coverage_text_is_normalized_to_enum_value(self):
        model = InspectionResult.from_legacy(
            {
                "metadata": {"triangle_count": 100},
                "selected_result": {
                    "inspection_coverage": {"geometry": "checked", "uv": "sampled:50/100 (50.0%)"},
                    "inspection_coverage_details": {"uv": {"coverage_ratio": 0.5}},
                },
            }
        )

        self.assertEqual(model.uv.status, "sampled")
        self.assertEqual(model.uv.coverage, "sampled")
        self.assertEqual(model.uv.details["legacy_coverage_text"], "sampled:50/100 (50.0%)")

    def test_validate_reports_incomplete_canonical_issue(self):
        model = InspectionResult.from_legacy({})
        invalid = replace(model, issues=[{"issue_id": "defect:uv_overlap"}])

        errors = invalid.validate()

        self.assertIn("issues[0].schema_version must be 1.0", errors)
        self.assertIn("issues[0].blocking must be boolean", errors)
        self.assertIn("issues[0].missing field: evidence", errors)


if __name__ == "__main__":
    unittest.main()
