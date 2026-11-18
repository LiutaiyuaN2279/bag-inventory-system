"""Run the preview's synthetic workflow tests, with explicit selection."""
import json
from pathlib import Path
import sys
import unittest

BACKEND = Path(__file__).resolve().parents[1]
MODULES = (
    "test_preview_seed_consistency",
    "test_purchase_receipt_flow",
    "test_quality_gate",
    "test_demo_role_log",
    "test_audit_traceability",
    "test_ocr_receipt_date",
)
EXPECTED_METHODS = 32
EXPECTED_SUBTESTS = 47


class CountResult(unittest.TextTestResult):
    subtests = 0

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)


def main():
    sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountResult).run(suite)
    print("FLOW_COUNTS " + json.dumps({
        "executed": result.testsRun,
        "subtests": result.subtests,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }))
    return int(not (
        result.wasSuccessful()
        and result.testsRun == EXPECTED_METHODS
        and result.subtests == EXPECTED_SUBTESTS
        and not result.skipped
    ))


if __name__ == "__main__":
    sys.exit(main())
