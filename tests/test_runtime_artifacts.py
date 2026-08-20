import json
import tempfile
import unittest
from pathlib import Path

from src.runtime_artifacts import validate_runtime_artifacts
from tests.artifact_fixtures import glb_bytes, png_bytes


class RuntimeArtifactTests(unittest.TestCase):
    def _write_valid_bundle(self, root: Path, *, varied: bool = True, model: bytes | None = None, image_size: int = 2):
        image_dir = root / "images"
        image_dir.mkdir()
        for name in ("view.png", "uv.png", "heatmap.png", "normal.png"):
            (image_dir / name).write_bytes(png_bytes(varied, image_size, image_size))
        model_path = root / "preview.glb"
        model_path.write_bytes(glb_bytes() if model is None else model)
        locator = root / "issue_locator.json"
        locator.write_text(json.dumps({"schema_version": "1.1", "source_issue_breakdown": []}), encoding="utf-8")
        script = root / "apply_issue_locator.py"
        script.write_text("print('ok')\n", encoding="utf-8")
        return {
            "views": [str(image_dir / "view.png")],
            "uv": str(image_dir / "uv.png"),
            "uv_heatmap": str(image_dir / "heatmap.png"),
            "normal": str(image_dir / "normal.png"),
            "model": str(model_path),
            "issue_locator": str(locator),
            "issue_selection_script": str(script),
        }

    def test_valid_required_artifacts_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            failures = validate_runtime_artifacts({}, self._write_valid_bundle(root))

            self.assertEqual(failures, [])

    def test_uniform_png_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_valid_bundle(Path(temp_dir), varied=False)

            failures = validate_runtime_artifacts({"metadata": {"uv_layer_count": 1}}, paths)

            self.assertEqual(
                {item["artifact"] for item in failures},
                {"views[0]", "uv", "uv_heatmap", "normal"},
            )

    def test_uniform_uv_evidence_is_allowed_when_uv_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_valid_bundle(Path(temp_dir), varied=False)

            failures = validate_runtime_artifacts({"metadata": {"uv_layer_count": 0, "uv_status": "not_present"}}, paths)

            self.assertEqual({item["artifact"] for item in failures}, {"views[0]", "normal"})

    def test_invalid_glb_container_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_valid_bundle(Path(temp_dir), model=b"glTFbad")

            failures = validate_runtime_artifacts({}, paths)

            self.assertEqual({item["artifact"] for item in failures}, {"model"})

    def test_large_two_color_heatmap_is_rejected_as_semantically_uninformative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = self._write_valid_bundle(Path(temp_dir), image_size=16)
            Path(paths["uv_heatmap"]).write_bytes(png_bytes(True, 16, 16, sparse=True))
            failures = validate_runtime_artifacts({"metadata": {"uv_layer_count": 1}}, paths)
            self.assertEqual({item["artifact"] for item in failures}, {"uv_heatmap"})

    def test_overlay_with_issue_marker_material_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._write_valid_bundle(root)
            overlay = root / "issue_overlay.glb"
            overlay.write_bytes(glb_bytes(marker=True))
            paths["model_overlay"] = str(overlay)
            row = {"metadata": {"issue_overlay_available": True, "issue_related_face_counts": {"uv_overlap": 3}}}
            self.assertEqual(validate_runtime_artifacts(row, paths), [])

    def test_overlay_without_marker_content_is_rejected_when_expected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._write_valid_bundle(root)
            overlay = root / "issue_overlay.glb"
            overlay.write_bytes(glb_bytes())
            paths["model_overlay"] = str(overlay)
            row = {"metadata": {"issue_overlay_available": True, "issue_related_face_counts": {"uv_overlap": 3}}}
            failures = validate_runtime_artifacts(row, paths)
            self.assertEqual({item["artifact"] for item in failures}, {"model_overlay"})

    def test_incomplete_output_reports_each_failure(self):
        failures = validate_runtime_artifacts({}, {"views": [], "uv": None, "model": "missing.glb"})
        self.assertEqual(
            {item["artifact"] for item in failures},
            {"views", "uv", "uv_heatmap", "normal", "model", "issue_locator", "issue_selection_script"},
        )


if __name__ == "__main__":
    unittest.main()
