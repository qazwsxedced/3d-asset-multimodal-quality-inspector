import json
import tempfile
import unittest
from pathlib import Path

from demo.services.asset_service import AssetDependencies, AssetService
from tests.artifact_fixtures import glb_bytes, png_bytes


class _FakeGradio:
    @staticmethod
    def Dropdown(**kwargs):
        return kwargs


class AssetServiceTests(unittest.TestCase):
    def test_normalize_uploaded_path_accepts_gradio_file_shapes(self):
        self.assertEqual(AssetService.normalize_uploaded_path("C:/model.fbx"), "C:/model.fbx")
        self.assertEqual(AssetService.normalize_uploaded_path({"path": "C:/model.obj"}), "C:/model.obj")
        self.assertEqual(AssetService.normalize_uploaded_path([{"path": "C:/model.blend"}]), "C:/model.blend")
        with self.assertRaises(ValueError):
            AssetService.normalize_uploaded_path(["C:/one.obj", "C:/two.obj"])

    def test_prepare_upload_uses_injected_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "asset.obj"
            source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
            runtime = root / "runtime"
            progress = []

            def run_blender_job(command, job_dir, progress_value, timeout):
                image_dir = job_dir / "images"
                image_dir.mkdir(parents=True)
                for name in ("view.png", "uv.png", "heatmap.png", "normal.png"):
                    (image_dir / name).write_bytes(png_bytes())
                (job_dir / "preview.glb").write_bytes(glb_bytes())
                (job_dir / "issue_locator.json").write_text(
                    json.dumps({"schema_version": "1.1", "source_issue_breakdown": []}),
                    encoding="utf-8",
                )
                (job_dir / "apply_issue_locator.py").write_text("print('ok')\n", encoding="utf-8")
                manifest = {
                    "id": "uploaded_asset_000000",
                    "images": {
                        "views": ["images/view.png"],
                        "uv": "images/uv.png",
                        "uv_heatmap": "images/heatmap.png",
                        "normal": "images/normal.png",
                        "model": "preview.glb",
                    },
                    "artifacts": {
                        "issue_locator": "issue_locator.json",
                        "issue_selection_script": "apply_issue_locator.py",
                    },
                    "metadata": {"asset_id": "uploaded_asset"},
                }
                (job_dir / "manifest.jsonl").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
                log = job_dir / "blender.log"
                log.write_text("ok", encoding="utf-8")
                return log

            def load_rows(manifest):
                row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
                return [row], {row["id"]: row}

            def resolve_image_paths(row, manifest):
                job_dir = manifest.parent
                return {
                    "views": [str(job_dir / "images" / "view.png")],
                    "uv": str(job_dir / "images" / "uv.png"),
                    "uv_heatmap": str(job_dir / "images" / "heatmap.png"),
                    "normal": str(job_dir / "images" / "normal.png"),
                    "model": str(job_dir / "preview.glb"),
                    "model_overlay": None,
                    "issue_locator": str(job_dir / "issue_locator.json"),
                    "issue_selection_script": str(job_dir / "apply_issue_locator.py"),
                }

            thresholds = {"max_upload_size_bytes": 1024 * 1024, "job_timeout_seconds": 10}
            adaptive = {"strategy": "default", "preview_views": 4, "preview_resolution": 192, "max_diagnostic_triangles": 1000}
            dependencies = AssetDependencies(
                run_blender_job=run_blender_job,
                find_blender=lambda: "blender",
                resolve_threshold_path=lambda _: root / "thresholds.json",
                load_thresholds=lambda _: thresholds,
                choose_adaptive_inspection_settings=lambda *_: adaptive,
                write_runtime_inspection_metadata=lambda *_: None,
                load_rows=load_rows,
                resolve_image_paths=resolve_image_paths,
                load_gradio=lambda: _FakeGradio,
                progress_update=lambda _progress, value, description: progress.append((value, description)),
            )

            result = AssetService(root, runtime, dependencies).prepare_uploaded_asset(str(source), "blender", "", object())

            self.assertEqual(result[0].endswith("manifest.jsonl"), True)
            self.assertEqual(result[1]["value"], "uploaded_asset_000000")
            self.assertEqual(result[2]["staging"]["source_file"], "asset.obj")
            self.assertEqual(result[2]["artifact_validation"]["status"], "passed")
            self.assertTrue(progress)


if __name__ == "__main__":
    unittest.main()
