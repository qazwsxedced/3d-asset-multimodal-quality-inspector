import tempfile
import unittest
from pathlib import Path

from demo.app import resolve_image_paths


class RuntimePathTests(unittest.TestCase):
    def test_manifest_paths_are_confined_to_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job = root / "job"
            job.mkdir()
            (job / "inside.png").write_bytes(b"image")
            (root / "outside.png").write_bytes(b"secret")
            manifest = job / "manifest.jsonl"
            row = {
                "images": {
                    "views": ["inside.png", "../outside.png"],
                    "uv": "../outside.png",
                },
                "artifacts": {"issue_locator": "../outside.png"},
            }

            paths = resolve_image_paths(row, manifest)

            self.assertEqual(paths["views"], [str((job / "inside.png").resolve())])
            self.assertIsNone(paths["uv"])
            self.assertIsNone(paths["issue_locator"])


if __name__ == "__main__":
    unittest.main()
