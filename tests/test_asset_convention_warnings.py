import unittest

from demo.app import build_complex_warnings, build_unified_issues
from src.threshold_config import DEFAULT_THRESHOLDS


class AssetConventionWarningTests(unittest.TestCase):
    def test_non_unit_scale_is_reported_as_information(self):
        warnings = build_complex_warnings(
            {
                "source_non_unit_scale_object_count": 1,
                "source_mesh_objects": [{"name": "Body", "non_unit_scale": True}],
            }
        )

        transform = next(item for item in warnings if item["code"] == "transform_anomaly")
        self.assertEqual(transform["level"], "info")
        self.assertIn("non_unit_scale_objects=1", transform["evidence"])
        self.assertIn("不一定是错误", transform["message_zh"])

        issues = build_unified_issues(
            {
                "source_non_unit_scale_object_count": 1,
                "source_mesh_objects": [{"name": "Body", "non_unit_scale": True}],
            },
            {"defect_types": [], "asset_profile": "Auto"},
            "Auto",
            dict(DEFAULT_THRESHOLDS),
        )
        issue = next(item for item in issues if item["issue_id"] == "warning:transform_anomaly")
        self.assertEqual(issue["locator"]["object_names"], ["Body"])

    def test_negative_scale_remains_a_warning(self):
        warnings = build_complex_warnings(
            {
                "source_negative_scale_object_count": 1,
                "source_non_unit_scale_object_count": 1,
                "source_mesh_objects": [{"name": "Mirror", "negative_scale": True, "non_unit_scale": True}],
            }
        )

        transform = next(item for item in warnings if item["code"] == "transform_anomaly")
        self.assertEqual(transform["level"], "warning")
        self.assertIn("法线翻转", transform["message_zh"])

    def test_missing_uv_warning_keeps_object_level_location(self):
        issues = build_unified_issues(
            {
                "source_missing_uv_object_count": 1,
                "source_uv_layer_count": 1,
                "texture_image_count": 1,
                "source_mesh_objects": [{"name": "NoUVPart", "uv_layer_count": 0}],
            },
            {"defect_types": [], "asset_profile": "Auto"},
            "Auto",
            dict(DEFAULT_THRESHOLDS),
        )

        issue = next(item for item in issues if item["issue_id"] == "warning:missing_uv")
        self.assertEqual(issue["locator"]["object_names"], ["NoUVPart"])
        self.assertEqual(issue["locator"]["object_count"], 1)


if __name__ == "__main__":
    unittest.main()
