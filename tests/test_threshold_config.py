import json
import tempfile
import unittest
from pathlib import Path

from demo.app import resolve_threshold_path
from src.threshold_config import DEFAULT_THRESHOLDS, load_thresholds, validate_threshold_file, validate_thresholds


class ThresholdConfigTests(unittest.TestCase):
    def test_repository_thresholds_are_valid(self):
        errors = validate_threshold_file(Path("config/inspection_thresholds.json"))
        self.assertEqual(errors, [])

    def test_unknown_and_out_of_range_values_are_rejected(self):
        errors = validate_thresholds({
            "max_uv_overlap_ratio": 2,
            "preview_views": 0,
            "typo_threshold": 1,
        })
        self.assertIn("max_uv_overlap_ratio: must be <= 1", errors)
        self.assertIn("preview_views: must be >= 1", errors)
        self.assertIn("unknown key: typo_threshold", errors)

    def test_min_texture_size_cannot_exceed_maximum(self):
        errors = validate_thresholds({"min_texture_size": 4096, "max_texture_size": 512})
        self.assertIn("min_texture_size: must be <= max_texture_size", errors)

    def test_invalid_file_falls_back_to_complete_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text(json.dumps({"max_faces": -1}), encoding="utf-8")

            loaded = load_thresholds(path)

            self.assertEqual(loaded, DEFAULT_THRESHOLDS)
            self.assertEqual(validate_threshold_file(path), ["max_faces: must be >= 1"])

    def test_valid_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text(json.dumps({"max_faces": 1234}), encoding="utf-8")

            loaded = load_thresholds(path)

            self.assertEqual(loaded["max_faces"], 1234)
            self.assertEqual(loaded["preview_views"], DEFAULT_THRESHOLDS["preview_views"])

    def test_string_paths_are_supported_by_shared_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text(json.dumps({"max_faces": 4321}), encoding="utf-8")

            self.assertEqual(load_thresholds(str(path))["max_faces"], 4321)
            self.assertEqual(validate_threshold_file(str(path)), [])

    def test_web_path_resolution_rejects_invalid_config_before_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text(json.dumps({"preview_resolution": 1}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid threshold config"):
                resolve_threshold_path(str(path))


if __name__ == "__main__":
    unittest.main()
