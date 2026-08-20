import unittest

from demo.app import build_locator_options, render_locator_details


class LocatorUiTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "selected_result": {
                "issues": [
                    {
                        "issue_id": "defect:uv_overlap",
                        "title_zh": "UV 重叠",
                        "title_en": "UV overlap",
                        "status": "fail",
                        "severity": "high",
                        "blocking": True,
                        "locator": {
                            "asset": "uv_heatmap",
                            "object_names": ["Body"],
                            "object_count": 1,
                            "related_face_count": 3,
                            "face_indices": [4, 9, 12],
                            "face_index_count": 3,
                            "face_index_truncated": False,
                        },
                    }
                ]
            }
        }

    def test_locator_options_are_selectable(self):
        options = build_locator_options(self.result, "中文")
        self.assertEqual(options, [("UV 重叠 · defect:uv_overlap", "defect:uv_overlap")])

    def test_locator_details_expose_object_and_face_evidence(self):
        details = render_locator_details("defect:uv_overlap", self.result)
        self.assertEqual(details["object_names"], ["Body"])
        self.assertEqual(details["face_indices"], [4, 9, 12])
        self.assertEqual(details["face_index_count"], 3)

    def test_material_locator_details_expose_material_and_source_objects(self):
        result = {
            "selected_result": {
                "issues": [{
                    "issue_id": "warning:pbr_channel_wiring",
                    "locator": {
                        "asset": "asset_info",
                        "material_names": ["Glass"],
                        "object_names": ["Lens"],
                        "object_count": 1,
                        "objects": [{"object_name": "Lens", "face_count": 24, "material_slot_index": 0}],
                    },
                }]
            }
        }

        details = render_locator_details("warning:pbr_channel_wiring", result)

        self.assertEqual(details["material_names"], ["Glass"])
        self.assertEqual(details["objects"][0]["face_count"], 24)


if __name__ == "__main__":
    unittest.main()
