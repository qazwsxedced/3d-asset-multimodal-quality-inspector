import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from inspection_config import choose_geometry_adaptive_settings, load_thresholds


class BlenderInspectionConfigTests(unittest.TestCase):
    def test_large_geometry_is_adapted_deterministically(self):
        args = argparse.Namespace(views=4, resolution=192)
        result = choose_geometry_adaptive_settings(
            args,
            {"max_diagnostic_triangles": 50_000},
            {"triangle_count": 1_100_000, "vertex_count": 700_000},
        )
        self.assertEqual(result["strategy"], "geometry_ultra_conservative")
        self.assertEqual(result["effective_views"], 1)
        self.assertEqual(result["effective_max_diagnostic_triangles"], 10_000)

    def test_missing_threshold_file_returns_safe_defaults(self):
        result = load_thresholds(Path("__missing_thresholds__.json"))
        self.assertEqual(result["max_faces"], 50_000)
        self.assertEqual(result["max_material_slots"], 8)


if __name__ == "__main__":
    unittest.main()
