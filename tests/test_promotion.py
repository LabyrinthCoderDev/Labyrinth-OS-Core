"""
tests/epistemic/test_promotion.py — Labyrinth-OS
=================================================
Epistemic pipeline tests: promotion pipeline.

Run with:
    python -m pytest tests/epistemic/test_promotion.py -v
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../promotion"))

from promotion_rules import PromotionRules, PromotionOutcome, PROMOTION_CONFIDENCE_THRESHOLD
from test_harness import TestHarness
from audit_trail import AuditTrail
from rollback_protocol import RollbackProtocol, RollbackReason


class TestPromotionPipeline(unittest.TestCase):

    def test_full_pipeline_approve(self):
        rules = PromotionRules()
        harness = TestHarness()
        trail = AuditTrail()

        hr = harness.run("lbl-001", 0.90, 0.10, 300.0, 20.0, 0.95)
        decision = rules.evaluate(
            label_id="lbl-001",
            confidence=0.96,
            consecutive_runs=5,
            harness_passed=hr.passed,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.APPROVED)

        record = trail.record(decision, approved_by="steward", harness_result=hr)
        self.assertTrue(trail.was_approved("lbl-001"))
        self.assertIsNotNone(record.harness_summary)

    def test_low_confidence_cascades_to_rejection(self):
        rules = PromotionRules()
        decision = rules.evaluate(
            label_id="lbl-002",
            confidence=0.50,
            consecutive_runs=5,
            harness_passed=True,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)

    def test_failed_harness_blocks_promotion(self):
        rules = PromotionRules()
        harness = TestHarness()
        hr = harness.run("lbl-003", 0.10, 0.90, 99999.0, 9999.0, 0.10)
        self.assertFalse(hr.passed)
        decision = rules.evaluate(
            label_id="lbl-003",
            confidence=0.96,
            consecutive_runs=5,
            harness_passed=hr.passed,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)

    def test_insufficient_runs_defers(self):
        rules = PromotionRules()
        decision = rules.evaluate(
            label_id="lbl-004",
            confidence=0.96,
            consecutive_runs=1,
            harness_passed=True,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.DEFERRED)

    def test_rollback_after_promotion(self):
        protocol = RollbackProtocol()
        record = protocol.rollback(
            label_id="lbl-005",
            reason=RollbackReason.PRODUCTION_FAILURE,
            ordered_by="steward",
            description="τ collapsed in production",
        )
        self.assertTrue(protocol.has_been_rolled_back("lbl-005"))
        self.assertEqual(record.reason, RollbackReason.PRODUCTION_FAILURE)

    def test_audit_trail_immutability(self):
        rules = PromotionRules()
        trail = AuditTrail()
        decision = rules.evaluate("lbl-006", 0.96, 5, True)
        audit_rec = trail.record(decision, approved_by="steward")
        with self.assertRaises(Exception):
            audit_rec.audit_id = 999  # type: ignore[misc]

    def test_confidence_threshold_boundary(self):
        rules = PromotionRules()
        at = rules.evaluate("lbl-007", PROMOTION_CONFIDENCE_THRESHOLD, 5, True)
        below = rules.evaluate("lbl-008", PROMOTION_CONFIDENCE_THRESHOLD - 0.001, 5, True)
        self.assertNotEqual(at.outcome, PromotionOutcome.REJECTED)
        self.assertEqual(below.outcome, PromotionOutcome.REJECTED)




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
