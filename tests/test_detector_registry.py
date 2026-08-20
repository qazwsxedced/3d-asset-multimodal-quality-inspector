import unittest
import tempfile
from pathlib import Path

from src.detector_registry import DEFAULT_DETECTOR_REGISTRY, DetectorContext, DetectorRegistry


class DetectorRegistryTests(unittest.TestCase):
    def test_default_detectors_are_registered_and_sorted(self):
        self.assertEqual(DEFAULT_DETECTOR_REGISTRY.names(), ("animation", "geometry", "materials", "runtime", "uv"))
        reports = DEFAULT_DETECTOR_REGISTRY.run(DetectorContext(metadata={"triangle_count": 12}, thresholds={}))
        self.assertEqual(reports["geometry"]["status"], "checked")
        self.assertEqual(reports["animation"]["status"], "not_applicable")

    def test_custom_detector_can_be_registered(self):
        registry = DetectorRegistry()

        @registry.register("custom")
        def custom(context):
            return {"status": "checked", "profile": context.asset_profile}

        report = registry.run(DetectorContext(metadata={}, thresholds={}, asset_profile="Realtime / XR"))
        self.assertEqual(report["custom"]["profile"], "Realtime / XR")

    def test_external_plugin_module_is_loaded_without_ui_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "sample_plugin.py"
            plugin.write_text(
                "def register_detectors(registry):\n"
                "    registry.register('external', lambda context: {'status': 'checked'})\n",
                encoding="utf-8",
            )
            registry = DetectorRegistry()
            records = registry.load_plugins([plugin])
            self.assertEqual(records[0]["status"], "loaded")
            self.assertEqual(records[0]["detectors"], ["external"])
            self.assertEqual(registry.run(DetectorContext(metadata={}, thresholds={}))["external"]["status"], "checked")

    def test_failed_plugin_registration_is_rolled_back(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "broken_plugin.py"
            plugin.write_text(
                "def register_detectors(registry):\n"
                "    registry.register('partial', lambda context: {'status': 'checked'})\n"
                "    raise RuntimeError('broken plugin')\n",
                encoding="utf-8",
            )
            registry = DetectorRegistry()
            records = registry.load_plugins([plugin])
            self.assertEqual(records[0]["status"], "failed")
            self.assertEqual(registry.names(), ())


if __name__ == "__main__":
    unittest.main()
