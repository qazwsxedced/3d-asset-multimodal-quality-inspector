import json
import unittest
from pathlib import Path


class RegressionContractTests(unittest.TestCase):
    def test_fixture_contract_is_complete_and_unique(self):
        root = Path(__file__).resolve().parents[1]
        cases = json.loads((root / "tests" / "inspection_test_cases.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 8)
        names = [case.get("name") for case in cases]
        self.assertEqual(len(names), len(set(names)))
        for case in cases:
            self.assertIn(case.get("format"), {"blend", "fbx", "obj"})
            self.assertIsInstance(case.get("expected"), list)
            self.assertIsInstance(case.get("assertions"), list)
            for assertion in case["assertions"]:
                self.assertTrue(assertion.get("path"))
                self.assertIn(assertion.get("op"), {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "nonempty"})


if __name__ == "__main__":
    unittest.main()
