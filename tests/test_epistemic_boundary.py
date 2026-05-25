"""
tests/epistemic/test_epistemic_boundary.py — Labyrinth-OS
==========================================================
Tests for the epistemic → execution boundary (Reality Gate).

These tests verify that the boundary invariants hold:
  - I11: Only VALID labels reach Reality Gate
  - I14: Promotions are audited
  - I2:  Gate is deterministic

Run with:
    python -m pytest tests/epistemic/test_epistemic_boundary.py -v
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/labeling"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../promotion"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../execution/reality_gate"))

from label_schema import LabelCategory, LabelRecord
from label_validator import LabelValidator
from promotion_rules import PromotionRules, PromotionOutcome
from audit_trail import AuditTrail
from gate_function import GateFunction, GateVerdict
from gate_binding import GateBinding
from gate_proof import GateProof
from gate_rejection import GateRejector, GateRejectionReason


class TestEpistemicBoundary(unittest.TestCase):
    """
    End-to-end tests: label → promotion → Reality Gate.
    """

    def _promoted_label(self, label_id: str = "lbl-e2e-001") -> tuple:
        """Create a fully promoted label ready for the Reality Gate."""
        rec = LabelRecord(
            label_id=label_id,
            category=LabelCategory.VALID,
            confidence=0.96,
            source="council",
            content="canonical-proposal-hash",
        )
        validator = LabelValidator()
        v_result = validator.validate_for_promotion(rec)

        rules = PromotionRules()
        decision = rules.evaluate(
            label_id=label_id,
            confidence=rec.confidence,
            consecutive_runs=5,
            harness_passed=True,
        )

        trail = AuditTrail()
        audit = trail.record(decision, approved_by="steward")

        return rec, decision, audit, trail

    # ── I11: Labeling Closure ─────────────────────────────────────────────────

    def test_only_valid_labels_pass_reality_gate(self):
        """Non-VALID label must be blocked at the Reality Gate."""
        gate = GateFunction()
        for category, should_pass in [
            ("VALID", True),
            ("UNCERTAIN", False),
            ("REJECTED", False),
            ("DEFERRED", False),
        ]:
            decision = gate.evaluate(
                label_id=f"lbl-{category}",
                confidence=0.96,
                promoted=True,
                label_category=category,
                timestamp=1000.0,
            )
            if should_pass:
                self.assertEqual(decision.verdict, GateVerdict.YES,
                                 f"{category} should be allowed")
            else:
                self.assertEqual(decision.verdict, GateVerdict.NO,
                                 f"{category} should be blocked")

    # ── I14: Promotion Auditability ───────────────────────────────────────────

    def test_promotion_always_logged(self):
        _, decision, audit, trail = self._promoted_label()
        self.assertEqual(decision.outcome, PromotionOutcome.APPROVED)
        self.assertTrue(trail.was_approved("lbl-e2e-001"))
        self.assertIsNotNone(audit.approved_by)

    def test_rejected_promotion_logged(self):
        rules = PromotionRules()
        trail = AuditTrail()
        decision = rules.evaluate("lbl-bad", 0.50, 5, False)
        self.assertEqual(decision.outcome, PromotionOutcome.REJECTED)
        trail.record(decision)
        self.assertFalse(trail.was_approved("lbl-bad"))

    # ── I2: Gate Determinism ─────────────────────────────────────────────────

    def test_gate_is_deterministic(self):
        gate = GateFunction()
        d1 = gate.evaluate("lbl-det", 0.96, True, "VALID", timestamp=1234.0)
        d2 = gate.evaluate("lbl-det", 0.96, True, "VALID", timestamp=1234.0)
        self.assertEqual(d1.decision_hash, d2.decision_hash)
        self.assertEqual(d1.verdict, d2.verdict)

    def test_gate_different_timestamp_different_hash(self):
        gate = GateFunction()
        d1 = gate.evaluate("lbl-ts", 0.96, True, "VALID", timestamp=1000.0)
        d2 = gate.evaluate("lbl-ts", 0.96, True, "VALID", timestamp=2000.0)
        self.assertNotEqual(d1.decision_hash, d2.decision_hash)

    # ── I10: Fail Closed ─────────────────────────────────────────────────────

    def test_gate_blocks_on_missing_promotion(self):
        gate = GateFunction()
        decision = gate.evaluate("lbl-nopromo", 0.96, promoted=False,
                                 label_category="VALID", timestamp=1000.0)
        self.assertEqual(decision.verdict, GateVerdict.NO)

    def test_gate_blocks_on_zero_confidence(self):
        gate = GateFunction()
        decision = gate.evaluate("lbl-zero-conf", 0.0, promoted=True,
                                 label_category="VALID", timestamp=1000.0)
        self.assertEqual(decision.verdict, GateVerdict.NO)

    # ── GateProof immutability ────────────────────────────────────────────────

    def test_gate_proof_verifies_correctly(self):
        proof = GateProof.issue(
            label_id="lbl-proof",
            decision_hash="a" * 64,
            audit_trail_hash="b" * 64,
            confidence=0.96,
            timestamp=1000.0,
        )
        self.assertTrue(proof.verify(
            label_id="lbl-proof",
            decision_hash="a" * 64,
            audit_trail_hash="b" * 64,
            confidence=0.96,
            timestamp=1000.0,
        ))

    def test_gate_proof_rejects_tampered_inputs(self):
        proof = GateProof.issue(
            label_id="lbl-proof",
            decision_hash="a" * 64,
            audit_trail_hash="b" * 64,
            confidence=0.96,
            timestamp=1000.0,
        )
        self.assertFalse(proof.verify(
            label_id="lbl-TAMPERED",
            decision_hash="a" * 64,
            audit_trail_hash="b" * 64,
            confidence=0.96,
            timestamp=1000.0,
        ))

    # ── GateBinding ───────────────────────────────────────────────────────────

    def test_gate_binding_all_rules_pass(self):
        binding = GateBinding()
        result = binding.check(
            promoted=True,
            has_audit_record=True,
            has_cgir_proof=True,
            confidence=0.96,
            category="VALID",
        )
        self.assertTrue(result.passed)

    def test_gate_binding_blocks_without_cgir_proof(self):
        binding = GateBinding()
        result = binding.check(
            promoted=True,
            has_audit_record=True,
            has_cgir_proof=False,  # missing
            confidence=0.96,
            category="VALID",
        )
        self.assertFalse(result.passed)

    # ── Rejection escalation ──────────────────────────────────────────────────

    def test_rejection_log_escalates_above_threshold(self):
        rejector = GateRejector(escalation_threshold=3)
        for i in range(3):
            rejector.reject(f"lbl-{i}", GateRejectionReason.NOT_PROMOTED, "test")
        self.assertTrue(rejector.should_escalate())




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
