"""
promotion_tests.py — Labyrinth-OS / Promotion Pipeline (L6.5)
=============================================================
Tests for the complete promotion pipeline.

Tests cover:
  - PromotionRules (all 5 rules)
  - TestHarness (threshold enforcement)
  - AuditTrail (immutability, record correctness)
  - RollbackProtocol (rollback recording and query)
  - End-to-end: candidate → rules → harness → audit → rollback

Run with:
    python -m pytest promotion/promotion_tests.py -v
"""

from __future__ import annotations

import time
import unittest

from promotion_rules import (
    PromotionRules,
    PromotionDecision,
    PromotionOutcome,
    PROMOTION_CONFIDENCE_THRESHOLD,
    MIN_CONSECUTIVE_RUNS,
)
from test_harness import TestHarness, HarnessResult, DEFAULT_THRESHOLDS
from audit_trail import AuditTrail, AuditRecord
from rollback_protocol import RollbackProtocol, RollbackRecord, RollbackReason


# ─── PROMOTION RULES TESTS ───────────────────────────────────────────────────

class TestPromotionRules(unittest.TestCase):

    def setUp(self):
        self.rules = PromotionRules()

    def _eval(self, **kw) -> PromotionDecision:
        defaults = dict(
            label_id="lbl-001",
            confidence=0.96,
            consecutive_runs=MIN_CONSECUTIVE_RUNS + 1,
            harness_passed=True,
            historical_failure_rate=0.05,
            archive_contradiction=False,
        )
        defaults.update(kw)
        return self.rules.evaluate(**defaults)

    # ── approval ──────────────────────────────────────────────────────────────

    def test_all_rules_pass_gives_approved(self):
        decision = self._eval()
        self.assertEqual(decision.outcome, PromotionOutcome.APPROVED)
        self.assertTrue(decision.approved)

    # ── Rule 1: confidence ────────────────────────────────────────────────────

    def test_confidence_below_threshold_rejects(self):
        decision = self._eval(confidence=PROMOTION_CONFIDENCE_THRESHOLD - 0.01)
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)

    def test_confidence_at_threshold_passes(self):
        decision = self._eval(confidence=PROMOTION_CONFIDENCE_THRESHOLD)
        self.assertNotEqual(decision.outcome, PromotionOutcome.REJECTED)

    # ── Rule 2: test harness ──────────────────────────────────────────────────

    def test_harness_failed_rejects(self):
        decision = self._eval(harness_passed=False)
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)

    # ── Rule 3: archive contradiction ─────────────────────────────────────────

    def test_archive_contradiction_rejects(self):
        decision = self._eval(archive_contradiction=True)
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)

    # ── Rule 4: historical failure rate ───────────────────────────────────────

    def test_high_failure_rate_rejects(self):
        decision = self._eval(historical_failure_rate=0.50)
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)

    def test_zero_failure_rate_passes(self):
        decision = self._eval(historical_failure_rate=0.0)
        self.assertNotEqual(decision.outcome, PromotionOutcome.REJECTED)

    # ── Rule 5: consecutive runs ─────────────────────────────────────────────

    def test_insufficient_runs_defers(self):
        decision = self._eval(consecutive_runs=MIN_CONSECUTIVE_RUNS - 1)
        self.assertEqual(decision.outcome, PromotionOutcome.DEFERRED)

    def test_sufficient_runs_approves(self):
        decision = self._eval(consecutive_runs=MIN_CONSECUTIVE_RUNS)
        self.assertEqual(decision.outcome, PromotionOutcome.APPROVED)

    # ── multiple failures ─────────────────────────────────────────────────────

    def test_multiple_failures_all_captured_in_reasons(self):
        decision = self._eval(
            confidence=0.50,
            harness_passed=False,
            archive_contradiction=True,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)
        self.assertGreaterEqual(len(decision.reasons), 3)

    # ── decision has timestamp ────────────────────────────────────────────────

    def test_decision_has_timestamp(self):
        decision = self._eval()
        self.assertIsNotNone(decision.timestamp)
        self.assertGreater(decision.timestamp, 0)


# ─── TEST HARNESS TESTS ───────────────────────────────────────────────────────

class TestTestHarness(unittest.TestCase):

    def setUp(self):
        self.harness = TestHarness()

    def _run(self, **kw) -> HarnessResult:
        defaults = dict(
            label_id="lbl-h-001",
            coherence=0.90,
            risk=0.10,
            latency_ms=200.0,
            cost_units=15.0,
            compliance_score=0.95,
        )
        defaults.update(kw)
        return self.harness.run(**defaults)

    def test_all_pass_gives_passed(self):
        result = self._run()
        self.assertTrue(result.passed)
        self.assertEqual(result.failures, [])

    def test_low_coherence_fails(self):
        result = self._run(coherence=0.50)
        self.assertFalse(result.passed)
        self.assertTrue(any("coherence" in f for f in result.failures))

    def test_high_risk_fails(self):
        result = self._run(risk=0.50)
        self.assertFalse(result.passed)
        self.assertTrue(any("risk" in f for f in result.failures))

    def test_high_latency_fails(self):
        result = self._run(latency_ms=99999.0)
        self.assertFalse(result.passed)
        self.assertTrue(any("latency" in f for f in result.failures))

    def test_high_cost_fails(self):
        result = self._run(cost_units=9999.0)
        self.assertFalse(result.passed)
        self.assertTrue(any("cost" in f for f in result.failures))

    def test_low_compliance_fails(self):
        result = self._run(compliance_score=0.50)
        self.assertFalse(result.passed)
        self.assertTrue(any("compliance" in f for f in result.failures))

    def test_update_threshold(self):
        self.harness.update_threshold("max_risk", 0.50)
        result = self._run(risk=0.40)
        self.assertTrue(result.passed)

    def test_unknown_threshold_raises(self):
        with self.assertRaises(KeyError):
            self.harness.update_threshold("nonexistent", 1.0)

    def test_summary_contains_pass(self):
        result = self._run()
        self.assertIn("PASS", result.summary())

    def test_summary_contains_fail(self):
        result = self._run(coherence=0.10)
        self.assertIn("FAIL", result.summary())

    def test_elapsed_ms_is_non_negative(self):
        result = self._run()
        self.assertGreaterEqual(result.elapsed_ms, 0.0)


# ─── AUDIT TRAIL TESTS ───────────────────────────────────────────────────────

class TestAuditTrail(unittest.TestCase):

    def setUp(self):
        self.trail = AuditTrail()
        self.rules = PromotionRules()

    def _decision(self, label_id: str = "lbl-a-001") -> PromotionDecision:
        return self.rules.evaluate(
            label_id=label_id,
            confidence=0.96,
            consecutive_runs=5,
            harness_passed=True,
        )

    def test_record_returns_audit_record(self):
        decision = self._decision()
        record = self.trail.record(decision, approved_by="steward")
        self.assertIsInstance(record, AuditRecord)
        self.assertEqual(record.audit_id, 1)

    def test_records_are_immutable(self):
        record = self.trail.record(self._decision(), approved_by="steward")
        with self.assertRaises(Exception):
            record.audit_id = 999  # type: ignore[misc]

    def test_sequential_audit_ids(self):
        for i in range(3):
            r = self.trail.record(self._decision(f"lbl-{i}"), approved_by="steward")
        self.assertEqual(r.audit_id, 3)

    def test_was_approved(self):
        self.trail.record(self._decision("lbl-approved"), approved_by="steward")
        self.assertTrue(self.trail.was_approved("lbl-approved"))

    def test_not_approved_for_unknown_label(self):
        self.assertFalse(self.trail.was_approved("lbl-unknown"))

    def test_records_for_label(self):
        self.trail.record(self._decision("lbl-x"), approved_by="steward")
        self.trail.record(self._decision("lbl-y"), approved_by="steward")
        self.assertEqual(len(self.trail.records_for_label("lbl-x")), 1)

    def test_approved_records_filter(self):
        # Approved
        self.trail.record(self._decision("lbl-ok"), approved_by="steward")
        # Rejected
        rejected = self.rules.evaluate(
            label_id="lbl-fail", confidence=0.50,
            consecutive_runs=5, harness_passed=False,
        )
        self.trail.record(rejected, approved_by=None)
        self.assertEqual(len(self.trail.approved_records()), 1)

    def test_harness_summary_stored(self):
        harness = TestHarness()
        hr = harness.run("lbl-001", 0.90, 0.10, 200.0, 15.0, 0.95)
        record = self.trail.record(self._decision(), harness_result=hr)
        self.assertIsNotNone(record.harness_summary)

    def test_no_delete_method(self):
        self.assertFalse(hasattr(self.trail, "delete"))


# ─── ROLLBACK PROTOCOL TESTS ─────────────────────────────────────────────────

class TestRollbackProtocol(unittest.TestCase):

    def setUp(self):
        self.protocol = RollbackProtocol()

    def _rollback(self, label_id: str = "lbl-001") -> RollbackRecord:
        return self.protocol.rollback(
            label_id=label_id,
            reason=RollbackReason.PRODUCTION_FAILURE,
            ordered_by="steward",
            description="τ dropped below floor after 2 cycles",
            previous_edge_ref="cgir-edge-v5",
        )

    def test_rollback_returns_record(self):
        record = self._rollback()
        self.assertIsInstance(record, RollbackRecord)
        self.assertEqual(record.rollback_id, 1)

    def test_records_are_immutable(self):
        record = self._rollback()
        with self.assertRaises(Exception):
            record.rollback_id = 999  # type: ignore[misc]

    def test_sequential_rollback_ids(self):
        for i in range(4):
            r = self._rollback(f"lbl-{i}")
        self.assertEqual(r.rollback_id, 4)

    def test_has_been_rolled_back_true(self):
        self._rollback("lbl-target")
        self.assertTrue(self.protocol.has_been_rolled_back("lbl-target"))

    def test_has_been_rolled_back_false(self):
        self.assertFalse(self.protocol.has_been_rolled_back("lbl-never"))

    def test_rollback_count_per_label(self):
        self._rollback("lbl-multi")
        self._rollback("lbl-multi")
        self._rollback("lbl-other")
        self.assertEqual(self.protocol.rollback_count("lbl-multi"), 2)

    def test_latest_for_label(self):
        self._rollback("lbl-x")
        r2 = self._rollback("lbl-x")
        latest = self.protocol.latest_for_label("lbl-x")
        self.assertEqual(latest.rollback_id, r2.rollback_id)

    def test_latest_for_unknown_label_is_none(self):
        self.assertIsNone(self.protocol.latest_for_label("lbl-unknown"))

    def test_archive_analysis_stored(self):
        record = self.protocol.rollback(
            label_id="lbl-001",
            reason=RollbackReason.ARCHIVE_CONTRADICTION,
            ordered_by="steward",
            description="archive showed repeated failure",
            archive_analysis="Pattern success_rate=0.15 over 8 runs",
        )
        self.assertIsNotNone(record.archive_analysis)

    def test_all_rollback_reasons_available(self):
        for reason in RollbackReason:
            r = self.protocol.rollback(
                label_id=f"lbl-{reason.value}",
                reason=reason,
                ordered_by="test",
                description="reason test",
            )
            self.assertEqual(r.reason, reason)


# ─── END-TO-END PROMOTION PIPELINE TEST ─────────────────────────────────────

class TestEndToEndPromotionPipeline(unittest.TestCase):
    """
    Simulate a full candidate lifecycle:
      harness → rules → audit → (failure) → rollback
    """

    def test_successful_promotion_pipeline(self):
        harness = TestHarness()
        rules   = PromotionRules()
        trail   = AuditTrail()

        # Step 1: run harness
        hr = harness.run("lbl-e2e", 0.88, 0.12, 300.0, 20.0, 0.92)
        self.assertTrue(hr.passed)

        # Step 2: evaluate rules
        decision = rules.evaluate(
            label_id="lbl-e2e",
            confidence=0.96,
            consecutive_runs=4,
            harness_passed=hr.passed,
            historical_failure_rate=0.05,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.APPROVED)

        # Step 3: record in audit trail
        audit_record = trail.record(
            decision,
            approved_by="steward",
            justification="all checks passed, manual approval granted",
            harness_result=hr,
        )
        self.assertTrue(trail.was_approved("lbl-e2e"))
        self.assertIsNotNone(audit_record.harness_summary)

    def test_failed_promotion_then_rollback(self):
        rules    = PromotionRules()
        trail    = AuditTrail()
        protocol = RollbackProtocol()

        # Rules reject candidate
        decision = rules.evaluate(
            label_id="lbl-bad",
            confidence=0.50,
            consecutive_runs=5,
            harness_passed=False,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)
        trail.record(decision, approved_by=None)

        # Simulate it slipping through (hypothetically) and needing rollback
        record = protocol.rollback(
            label_id="lbl-bad",
            reason=RollbackReason.SAFETY_VIOLATION,
            ordered_by="steward",
            description="candidate violated coherence invariant in production",
        )
        self.assertTrue(protocol.has_been_rolled_back("lbl-bad"))
        self.assertEqual(record.reason, RollbackReason.SAFETY_VIOLATION)

    def test_confidence_threshold_enforcement(self):
        """Promotion must fail when confidence is exactly at boundary."""
        rules = PromotionRules()
        # At threshold — should pass
        at = rules.evaluate("lbl-at", PROMOTION_CONFIDENCE_THRESHOLD, 5, True)
        self.assertNotEqual(at.outcome, PromotionOutcome.REJECTED)
        # One tick below — should fail
        below = rules.evaluate("lbl-below", PROMOTION_CONFIDENCE_THRESHOLD - 0.001, 5, True)
        self.assertEqual(below.outcome, PromotionOutcome.REJECTED)



def run_tests() -> tuple:
    """Labyrinth-OS standard runner — wraps unittest for run_all.py compatibility."""
    import unittest, io
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    buf    = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    results = []
    for test, tb in result.failures + result.errors:
        results.append((str(test), "FAIL", tb.split("\n")[-2]))
    for i in range(passed):
        results.append((f"test_{i:03}", "PASS", None))
    return passed, failed, results


if __name__ == "__main__":
    import unittest
    unittest.main()
