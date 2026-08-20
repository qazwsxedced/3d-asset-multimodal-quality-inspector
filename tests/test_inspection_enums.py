import unittest

from src.inspection_enums import CheckStatus, CoverageStatus, IssueStatus, Severity, enum_value, enum_values


class InspectionEnumTests(unittest.TestCase):
    def test_check_status_and_coverage_are_distinct(self):
        self.assertEqual(CheckStatus.PASSED.value, "passed")
        self.assertEqual(CheckStatus.FAILED.value, "failed")
        self.assertEqual(CoverageStatus.CHECKED.value, "checked")
        self.assertNotEqual(CheckStatus.PASSED.value, CoverageStatus.CHECKED.value)

    def test_issue_and_severity_vocabularies_are_serializable(self):
        self.assertIn(IssueStatus.NEAR_THRESHOLD.value, enum_values(IssueStatus))
        self.assertIn(Severity.BLOCKER.value, enum_values(Severity))
        self.assertEqual(enum_value("unknown", Severity, Severity.INFO), "info")
        self.assertEqual(enum_value(Severity.HIGH, Severity, Severity.INFO), "high")


if __name__ == "__main__":
    unittest.main()
