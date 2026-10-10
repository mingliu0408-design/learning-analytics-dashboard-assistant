"""Post-Gold artifact-only validation tests; skipped before the access receipt exists."""

from __future__ import annotations

import unittest

from ..constants import ACCESS_RECEIPT_PATH, BINDING_PATH
from ..validate_final_scoring import validate_outputs


@unittest.skipUnless(
    ACCESS_RECEIPT_PATH.exists() and BINDING_PATH.exists(),
    "post-Gold immutable artifacts do not yet exist",
)
class ArtifactValidationTests(unittest.TestCase):
    def test_01_complete_artifact_validation(self) -> None:
        result = validate_outputs(recompute_bootstrap=True)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["bootstrap_recomputed"])

    def test_02_no_real_scoring_rerun_is_needed_for_validation(self) -> None:
        result = validate_outputs(recompute_bootstrap=False)
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
