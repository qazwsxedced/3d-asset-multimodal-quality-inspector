import unittest

from src.quality_scoring import compute_health_score


def _base_metadata() -> dict:
    return {
        "vertex_count": 64,
        "face_count": 32,
        "triangle_count": 32,
        "uv_layer_count": 1,
        "uv_status": "present",
        "material_count": 1,
        "texture_image_count": 1,
        "pbr_channel_issue_count": 0,
        "loading_risk": "low",
        "estimated_draw_calls": 1,
        "estimated_texture_memory_bytes": 1024,
    }


class QualityScoringRegressionTests(unittest.TestCase):
    def test_detected_defect_cannot_improve_health_score(self):
        clean = compute_health_score(
            _base_metadata(), [], asset_profile="Realtime / XR"
        )
        defective = compute_health_score(
            dict(_base_metadata(), uv_overlap_ratio=0.2),
            ["uv_overlap"],
            asset_profile="Realtime / XR",
        )
        self.assertLessEqual(defective["score"], clean["score"])
        self.assertLessEqual(defective["profile_fit_score"], clean["profile_fit_score"])

    def test_adding_another_issue_cannot_improve_score(self):
        one_issue = compute_health_score(
            dict(_base_metadata(), uv_overlap_ratio=0.2),
            ["uv_overlap"],
            asset_profile="Realtime / XR",
        )
        two_issues = compute_health_score(
            dict(_base_metadata(), uv_overlap_ratio=0.2, missing_texture_count=1),
            ["uv_overlap", "missing_textures"],
            asset_profile="Realtime / XR",
        )
        self.assertLessEqual(two_issues["score"], one_issue["score"])
        self.assertLessEqual(two_issues["profile_fit_score"], one_issue["profile_fit_score"])

    def test_lower_sampled_coverage_reduces_confidence(self):
        complete = compute_health_score(
            _base_metadata(), [], asset_profile="Realtime / XR"
        )
        sampled = compute_health_score(
            dict(
                _base_metadata(),
                uv_analysis_sampled=True,
                uv_analysis_coverage_ratio=0.5,
            ),
            [],
            asset_profile="Realtime / XR",
        )
        self.assertEqual(complete["profile_fit_confidence"], "high")
        self.assertEqual(sampled["profile_fit_confidence"], "medium")
        self.assertLess(sampled["profile_fit_coverage"], complete["profile_fit_coverage"])


if __name__ == "__main__":
    unittest.main()
