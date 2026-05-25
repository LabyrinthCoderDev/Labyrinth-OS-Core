"""
tests/epistemic/test_labeling.py — Labyrinth-OS
================================================
Epistemic pipeline tests: labeling layer.

These tests exercise the full labeling pipeline from a black-box perspective.

Run with:
    python -m pytest tests/epistemic/test_labeling.py -v
"""

from __future__ import annotations

import sys
import os
import time
import unittest

# Allow importing from the labeling package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/labeling"))

from label_schema import LabelCategory, ConfidenceTier, RejectionReason, LabelRecord
from label_validator import LabelValidator, ValidationResult, PROMOTION_CONFIDENCE_THRESHOLD
from confidence_meter import ConfidenceMeter


class TestLabelingPipeline(unittest.TestCase):
    """Black-box tests of the labeling pipeline."""

    def test_high_confidence_valid_label_passes_all_checks(self):
        """A well-formed VALID label with high confidence passes every check."""
        rec = LabelRecord(
            label_id="pipeline-001",
            category=LabelCategory.VALID,
            confidence=0.95,
            source="council",
            content="test-proposal-hash",
        )
        # Use separate validators — each has its own seen-id registry
        base_result = LabelValidator().validate(rec)
        promo_result = LabelValidator().validate_for_promotion(rec)
        self.assertTrue(base_result)
        self.assertTrue(promo_result)

    def test_rejected_label_carries_reason(self):
        """A REJECTED label must carry a RejectionReason."""
        rec = LabelRecord(
            label_id="pipeline-002",
            category=LabelCategory.REJECTED,
            confidence=0.10,
            source="watcher_a",
            content="bad-proposal",
            rejection_reason=RejectionReason.CONFIDENCE_BELOW_THRESHOLD,
        )
        validator = LabelValidator()
        result = validator.validate(rec)
        self.assertTrue(result)  # schema is valid — has reason

    def test_label_without_reason_is_schema_violation(self):
        rec = LabelRecord(
            label_id="pipeline-003",
            category=LabelCategory.REJECTED,
            confidence=0.10,
            source="watcher_a",
            content="bad",
        )
        validator = LabelValidator()
        result = validator.validate(rec)
        self.assertFalse(result)
        self.assertEqual(result.rejection_reason, RejectionReason.SCHEMA_VIOLATION)

    def test_confidence_meter_and_validator_agree_on_tier(self):
        """ConfidenceMeter tier matches LabelRecord tier for same confidence."""
        meter = ConfidenceMeter()
        sample = meter.compute("lbl-tier", 0.90, 0.85, 0.88)
        rec = LabelRecord(
            label_id="lbl-tier",
            category=LabelCategory.VALID,
            confidence=sample.score,
            source="test",
            content="x",
        )
        self.assertEqual(rec.confidence_tier(), ConfidenceTier.HIGH)

    def test_duplicate_labels_are_rejected(self):
        validator = LabelValidator()
        rec1 = LabelRecord("dup-001", LabelCategory.VALID, 0.90, "council", "x")
        rec2 = LabelRecord("dup-001", LabelCategory.VALID, 0.90, "council", "y")
        validator.validate(rec1)
        result = validator.validate(rec2)
        self.assertFalse(result)
        self.assertEqual(result.rejection_reason, RejectionReason.DUPLICATE_LABEL)

    def test_promotion_threshold_is_stricter_than_valid_floor(self):
        """Promotion threshold (0.85) > valid floor (0.60)."""
        self.assertGreater(PROMOTION_CONFIDENCE_THRESHOLD, 0.60)

    def test_declining_confidence_detected_by_meter(self):
        meter = ConfidenceMeter()
        # Build up high-confidence history
        for _ in range(10):
            meter.compute("x", 0.95, 0.95, 0.95)
        # Then simulate degraded performance
        for _ in range(10):
            meter.compute("x", 0.10, 0.10, 0.10)
        self.assertTrue(meter.is_declining())




def run_tests() -> tuple:
    """Labyrinth-OS standard runner — wraps unittest for run_all.py compatibility."""
    import unittest, io, sys, os
    # Add all relevant paths
    _BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    for _sub in [
        os.path.join(_BASE, 'epistemic', 'labeling'),
        os.path.join(_BASE, 'epistemic', 'archive'),
        os.path.join(_BASE, 'promotion'),
        os.path.join(_BASE, 'execution', 'observability'),
        os.path.join(_BASE, 'execution', 'pre_cgir_gate'),
    ]:
        if os.path.isdir(_sub) and _sub not in sys.path:
            sys.path.insert(0, _sub)

    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    buf    = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    results = []
    for test, tb in result.failures + result.errors:
        results.append((str(test), "FAIL", tb.strip().split("\n")[-1]))
    for i in range(passed):
        results.append((f"test_{i:03}", "PASS", None))
    return passed, failed, results


if __name__ == "__main__":
    import unittest
    unittest.main()
