import unittest

from demo.app import build_pbr_issue_breakdown
from src.inspection_schema import normalize_issue


class MaterialLocalizationTests(unittest.TestCase):
    def test_pbr_issue_maps_material_to_source_objects(self):
        metadata = {
            "source_material_usage": {
                "Glass": [{
                    "object_name": "Lens",
                    "face_count": 24,
                    "material_slot_index": 0,
                }]
            },
            "pbr_material_reports": [{
                "name": "Glass",
                "issues": ["Normal:expected_non_color"],
            }],
        }

        details = build_pbr_issue_breakdown(metadata)

        self.assertEqual(details[0]["object_names"], ["Lens"])
        self.assertEqual(details[0]["objects"][0]["face_count"], 24)

    def test_normalized_material_issue_exposes_object_locator(self):
        issue = normalize_issue({
            "issue_id": "warning:pbr_channel_wiring",
            "material_details": [{
                "material": "Glass",
                "object_names": ["Lens"],
                "objects": [{"object_name": "Lens", "face_count": 24}],
            }],
        })

        self.assertEqual(issue["locator"]["object_names"], ["Lens"])
        self.assertEqual(issue["locator"]["material_names"], ["Glass"])


if __name__ == "__main__":
    unittest.main()
