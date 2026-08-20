import unittest

from src.inspection_schema import ISSUE_SCHEMA_VERSION, normalize_issue, normalize_issue_list


class InspectionSchemaTests(unittest.TestCase):
    def test_normalize_issue_adds_canonical_fields_and_object_location(self):
        issue = normalize_issue(
            {
                "issue_id": "defect:uv_overlap",
                "title_zh": "UV 重叠",
                "severity": "medium",
                "status": "fail",
                "blocking": True,
                "impact_zh": "可能污染烘焙。",
                "fix_zh": "重新展开 UV。",
                "recheck_zh": "重叠率低于阈值。",
                "locator": {"asset": "uv_heatmap"},
            },
            {
                "source_issue_breakdown": [
                    {
                        "object_name": "Body",
                        "face_index_space": "source_mesh_base",
                        "object_selector": {"topology_fingerprint": "abc"},
                        "related_face_counts": {"uv_overlap": 12},
                        "related_face_indices": {"uv_overlap": [4, 9]},
                    },
                ],
                "issue_related_face_indices": {"uv_overlap": [4, 9]},
                "issue_related_face_counts": {"uv_overlap": 12},
                "issue_face_index_truncated": {"uv_overlap": True},
            },
        )
        self.assertEqual(issue["schema_version"], ISSUE_SCHEMA_VERSION)
        self.assertEqual(issue["category"], "geometry")
        self.assertEqual(issue["location"]["object_names"], ["Body"])
        self.assertEqual(issue["location"]["face_indices"], [4, 9])
        self.assertTrue(issue["location"]["face_index_truncated"])
        self.assertEqual(issue["location"]["face_index_space"], "source_mesh_base")
        self.assertEqual(issue["location"]["identity_validation"], "object_name_then_topology_fingerprint")
        self.assertEqual(issue["location"]["objects"][0]["object_selector"]["topology_fingerprint"], "abc")
        self.assertEqual(issue["impact"]["zh"], "可能污染烘焙。")
        self.assertIs(issue["locator"], issue["location"])

    def test_normalize_issue_list_makes_duplicate_ids_unique(self):
        issues = normalize_issue_list([
            {"issue_id": "warning:test", "status": "info"},
            {"issue_id": "warning:test", "status": "info"},
        ])
        self.assertEqual([item["issue_id"] for item in issues], ["warning:test", "warning:test#2"])


if __name__ == "__main__":
    unittest.main()
