import json
import tempfile
import unittest
from pathlib import Path

from src.asset_staging import stage_asset


class AssetStagingTests(unittest.TestCase):
    def test_obj_mtl_and_texture_are_staged_with_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            job_dir = root / "job"
            source_dir.mkdir()
            (source_dir / "model.obj").write_text("mtllib model.mtl\nv 0 0 0\n", encoding="utf-8")
            (source_dir / "model.mtl").write_text("newmtl Material\nmap_Kd albedo.png\n", encoding="utf-8")
            (source_dir / "albedo.png").write_bytes(b"not-a-real-png-for-staging-test")

            result = stage_asset(source_dir / "model.obj", job_dir, max_size_bytes=1024 * 1024)

            self.assertTrue(result.staged_path.exists())
            self.assertEqual(set(result.sidecar_files), {"model.mtl", "albedo.png"})
            self.assertTrue((job_dir / "model.mtl").exists())
            self.assertTrue((job_dir / "albedo.png").exists())
            record = json.loads((job_dir / "staging.json").read_text(encoding="utf-8"))
            self.assertEqual(record["source_file"], "model.obj")
            self.assertEqual(len(record["source_sha256"]), 64)

    def test_upload_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "model.obj"
            source.write_bytes(b"too large")
            with self.assertRaises(ValueError):
                stage_asset(source, root / "job", max_size_bytes=1)


if __name__ == "__main__":
    unittest.main()
