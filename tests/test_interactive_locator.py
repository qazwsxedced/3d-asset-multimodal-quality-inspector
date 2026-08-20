import unittest

from src.interactive_locator import (
    INTERACTIVE_LOCATOR_JS,
    build_pickable_objects,
    render_interactive_locator_html,
    resolve_object_pick,
)


class InteractiveLocatorTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "metadata": {
                "source_mesh_objects": [
                    {"name": "Frame", "face_count": 12, "vertex_count": 20},
                    {"name": "Lens", "face_count": 8, "vertex_count": 16},
                ]
            },
            "selected_result": {
                "issues": [
                    {
                        "issue_id": "uv_overlap",
                        "title_zh": "UV 重叠",
                        "title_en": "UV overlap",
                        "severity": "high",
                        "blocking": True,
                        "locator": {
                            "object_names": ["Lens"],
                            "objects": [{"object_name": "Lens", "face_count": 3}],
                            "face_indices": [1, 4, 6],
                        },
                    }
                ]
            },
        }

    def test_pickable_objects_merge_object_and_issue_evidence(self):
        rows = build_pickable_objects(self.result)
        lens = next(item for item in rows if item["object_name"] == "Lens")
        self.assertEqual(lens["face_count"], 8)
        self.assertEqual(lens["issue_ids"], ["uv_overlap"])
        self.assertEqual(lens["issue_titles"], ["UV 重叠"])

    def test_object_pick_selects_issue(self):
        selected = resolve_object_pick(" lens ", self.result)
        self.assertEqual(selected["status"], "matched")
        self.assertEqual(selected["issue_id"], "uv_overlap")
        self.assertEqual(selected["locator"]["face_indices"], [1, 4, 6])

    def test_object_without_issue_is_explicit(self):
        selected = resolve_object_pick("Frame", self.result)
        self.assertEqual(selected["status"], "object_without_issue")

    def test_overlay_face_pick_can_resolve_issue_without_source_object_name(self):
        selected = resolve_object_pick(
            "issue_overlay",
            self.result,
            issue_id="defect:uv_overlap",
            face_id=17,
        )
        self.assertEqual(selected["status"], "matched")
        self.assertEqual(selected["issue_id"], "uv_overlap")
        self.assertEqual(selected["picked_face_id"], 17)
        self.assertEqual(selected["picked_face_coordinate_space"], "overlay_triangle")

    def test_html_contains_safe_picker_data_without_script(self):
        rendered = render_interactive_locator_html("C:/runtime/model.glb", self.result, issue_overlay_path="C:/runtime/issue_overlay.glb")
        self.assertIn("asset-interactive-locator", rendered)
        self.assertIn("/gradio_api/file=C:/runtime/model.glb", rendered)
        self.assertIn("/gradio_api/file=C:/runtime/issue_overlay.glb", rendered)
        self.assertIn("UV 重叠", rendered)
        self.assertNotIn("<script", rendered.lower())

    def test_browser_locator_load_is_lazy_and_scan_is_debounced(self):
        """The optional 3D picker must not compete with Gradio's upload flow."""
        self.assertIn("const ensureLoader = async ()", INTERACTIVE_LOCATOR_JS)
        self.assertIn("if (!force)", INTERACTIVE_LOCATOR_JS)
        self.assertIn("let scanTimer = null", INTERACTIVE_LOCATOR_JS)
        self.assertIn("window.setTimeout", INTERACTIVE_LOCATOR_JS)
        self.assertIn("3D 定位器已延迟加载", INTERACTIVE_LOCATOR_JS)


if __name__ == "__main__":
    unittest.main()
