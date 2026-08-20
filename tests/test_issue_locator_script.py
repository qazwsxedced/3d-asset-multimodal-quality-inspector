import unittest

from src.issue_locator_script import build_blender_selection_script


class IssueLocatorScriptTests(unittest.TestCase):
    def test_script_embeds_locator_and_supports_targeted_selection(self):
        script = build_blender_selection_script({
            "issue_related_face_counts": {"uv_overlap": 3},
            "source_issue_breakdown": [{
                "object_name": "Body's Mesh",
                "face_count": 12,
                "object_selector": {
                    "object_name": "Body's Mesh",
                    "vertex_count": 8,
                    "face_count": 12,
                    "topology_fingerprint": "abc123",
                    "world_location": [0.0, 0.0, 0.0],
                },
                "related_face_counts": {"uv_overlap": 3},
                "related_face_indices": {"uv_overlap": [2, 5, 8]},
            }],
        })
        self.assertIn("select_issue_faces", script)
        self.assertIn('ISSUE_ID = None', script)
        self.assertIn("ALLOW_TOPOLOGY_MISMATCH = False", script)
        self.assertIn("topology_mismatches", script)
        self.assertIn("identity_mismatches", script)
        self.assertIn("ambiguous_objects", script)
        self.assertIn("invalid_face_indices", script)
        self.assertIn("_resolve_object", script)
        self.assertIn("base mesh", script)
        self.assertIn("_topology_fingerprint", script)
        self.assertIn("base64.b64decode", script)
        self.assertNotIn("Body's Mesh", script)
        compile(script, "apply_issue_locator.py", "exec")


if __name__ == "__main__":
    unittest.main()
