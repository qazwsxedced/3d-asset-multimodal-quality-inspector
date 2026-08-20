import json
import unittest
from pathlib import Path

from src.quality_scoring import compute_health_score, load_scoring_config, scoring_config_hash


class ScoringConfigTests(unittest.TestCase):
    def test_default_config_is_loaded_and_fingerprinted(self):
        config = load_scoring_config()
        self.assertEqual(config["config_version"], "1.0")
        self.assertEqual(len(scoring_config_hash(config)), 64)

    def test_profile_weight_override_changes_only_policy_score(self):
        metadata = {
            "vertex_count": 10,
            "face_count": 10,
            "triangle_count": 10,
            "uv_layer_count": 1,
            "uv_status": "present",
            "material_count": 1,
            "texture_image_count": 1,
            "loading_risk": "low",
        }
        config = load_scoring_config()
        altered = json.loads(json.dumps(config))
        altered["profiles"]["realtime_or_xr"]["weights"]["runtime"] = 0.8
        baseline = compute_health_score(metadata, [], asset_profile="Realtime / XR", scoring_config=config)
        changed = compute_health_score(metadata, [], asset_profile="Realtime / XR", scoring_config=altered)
        self.assertEqual(baseline["score"], changed["score"])
        self.assertNotEqual(baseline["score_config_hash"], changed["score_config_hash"])
        self.assertEqual(changed["profile_fit_weights"]["runtime"], 0.8)


if __name__ == "__main__":
    unittest.main()
