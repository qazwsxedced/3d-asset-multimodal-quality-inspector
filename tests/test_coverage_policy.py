import unittest

from demo.app import build_inspection_coverage, build_inspection_coverage_details
from src.coverage_policy import has_material_statistics, has_runtime_statistics
from src.detector_registry import DEFAULT_DETECTOR_REGISTRY, DetectorContext
from src.quality_scoring import compute_health_score


class CoveragePolicyTests(unittest.TestCase):
    def test_material_coverage_does_not_require_texture_images(self):
        metadata = {"material_count": 2, "texture_image_count": 0}

        self.assertEqual(build_inspection_coverage(metadata)["materials"], "checked")
        self.assertEqual(build_inspection_coverage_details(metadata)["materials"]["status"], "checked")
        self.assertEqual(
            DEFAULT_DETECTOR_REGISTRY.run(DetectorContext(metadata=metadata, thresholds={}))["materials"]["status"],
            "checked",
        )

    def test_empty_or_invalid_statistics_are_not_treated_as_checked(self):
        self.assertFalse(has_material_statistics({"pbr_material_reports": []}))
        self.assertFalse(has_material_statistics({"material_count": None}))
        self.assertFalse(has_runtime_statistics({"loading_risk": "unknown"}))
        self.assertFalse(has_runtime_statistics({"file_size_bytes": 0}))

    def test_runtime_coverage_accepts_any_runtime_statistic(self):
        metadata = {"file_size_bytes": 1024}

        self.assertEqual(build_inspection_coverage(metadata)["runtime"], "checked")
        self.assertEqual(
            DEFAULT_DETECTOR_REGISTRY.run(DetectorContext(metadata=metadata, thresholds={}))["runtime"]["status"],
            "checked",
        )

    def test_scoring_keeps_material_component_when_images_are_absent(self):
        metadata = {
            "vertex_count": 64,
            "face_count": 32,
            "triangle_count": 32,
            "material_count": 2,
            "texture_image_count": 0,
            "pbr_channel_issue_count": 0,
        }

        score = compute_health_score(metadata, [], asset_profile="Visual display / open surface")
        materials = next(
            item for item in score["profile_fit_contributions"]
            if item["component"] == "materials"
        )
        self.assertEqual(materials["status"], "checked")

    def test_animation_probe_is_reported_as_sampled(self):
        metadata = {
            "source_has_animation": True,
            "deformation_self_intersection_sample_count": 3,
        }

        self.assertEqual(build_inspection_coverage(metadata)["animation"], "sampled")
        details = build_inspection_coverage_details(metadata)["animation"]
        self.assertEqual(details["status"], "sampled")
        self.assertEqual(details["coverage_ratio"], 0.5)
        detector = DEFAULT_DETECTOR_REGISTRY.run(DetectorContext(metadata=metadata, thresholds={}))['animation']
        self.assertEqual(detector['status'], 'sampled')

    def test_animation_without_actions_is_binding_only_not_full_playback_check(self):
        metadata = {
            "source_has_armature": True,
            "source_has_animation": False,
            "rigged_mesh_count": 1,
            "animation_inspection_status": "binding_only",
            "animation_playability": "not_tested_no_actions",
        }

        self.assertEqual(build_inspection_coverage(metadata)["animation"], "checked")
        details = build_inspection_coverage_details(metadata)["animation"]
        self.assertEqual(details["status"], "checked")
        self.assertEqual(details["coverage_ratio"], 1.0)
        self.assertIn("没有可供播放采样的动作", details["note_zh"])

    def test_animation_with_no_rigged_mesh_is_not_checked(self):
        metadata = {
            "source_has_animation": True,
            "source_has_armature": True,
            "rigged_mesh_count": 0,
            "animation_inspection_status": "not_checked",
            "animation_playability": "not_tested_no_rigged_mesh",
        }

        self.assertEqual(build_inspection_coverage(metadata)["animation"], "not_checked")
        self.assertEqual(build_inspection_coverage_details(metadata)["animation"]["coverage_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
