"""
tests/integration/test_labeling_to_reality_gate.py — Labyrinth-OS
==================================================================
Integration test: labeling pipeline → Reality Gate.

Verifies the complete path from a raw label through validation, promotion,
and Reality Gate evaluation, ending with a GateProof.

Run with:
    python -m pytest tests/integration/test_labeling_to_reality_gate.py -v
"""

from __future__ import annotations

import sys
import os
import hashlib
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/labeling"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../promotion"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../execution/reality_gate"))

from label_schema import LabelCategory, LabelRecord
from label_validator import LabelValidator
from promotion_rules import PromotionRules, PromotionOutcome
from test_harness import TestHarness
from audit_trail import AuditTrail
from gate_function import GateFunction, GateVerdict
from gate_proof import GateProof


class TestLabelingToRealityGate(unittest.TestCase):

    def test_happy_path_label_crosses_reality_gate(self):
        """
        Full happy-path integration:
        Create label → validate → promote → Reality Gate YES → GateProof
        """
        # Step 1: Create label
        rec = LabelRecord(
            label_id="int-001",
            category=LabelCategory.VALID,
            confidence=0.96,
            source="council",
            content="proposal-abc123",
        )

        # Step 2: Validate
        validator = LabelValidator()
        v = validator.validate_for_promotion(rec)
        self.assertTrue(v, f"Validation failed: {v.errors}")

        # Step 3: Test harness
        harness = TestHarness()
        hr = harness.run("int-001", 0.88, 0.12, 300.0, 20.0, 0.95)
        self.assertTrue(hr.passed)

        # Step 4: Promotion rules
        rules = PromotionRules()
        decision = rules.evaluate(
            label_id="int-001",
            confidence=rec.confidence,
            consecutive_runs=5,
            harness_passed=hr.passed,
        )
        self.assertEqual(decision.outcome, PromotionOutcome.APPROVED)

        # Step 5: Audit trail
        trail = AuditTrail()
        audit = trail.record(decision, approved_by="steward", harness_result=hr)
        self.assertTrue(trail.was_approved("int-001"))

        # Step 6: Reality Gate
        gate = GateFunction()
        gate_decision = gate.evaluate(
            label_id="int-001",
            confidence=rec.confidence,
            promoted=decision.approved,
            label_category=rec.category.value,
            timestamp=1000.0,
        )
        self.assertEqual(gate_decision.verdict, GateVerdict.YES)

        # Step 7: Issue proof
        audit_hash = hashlib.sha256(
            f"{audit.audit_id}|{audit.label_id}|{audit.outcome}".encode()
        ).hexdigest()
        proof = GateProof.issue(
            label_id="int-001",
            decision_hash=gate_decision.decision_hash,
            audit_trail_hash=audit_hash,
            confidence=rec.confidence,
            timestamp=1000.0,
        )
        self.assertTrue(proof.verify(
            label_id="int-001",
            decision_hash=gate_decision.decision_hash,
            audit_trail_hash=audit_hash,
            confidence=rec.confidence,
            timestamp=1000.0,
        ))

    def test_low_confidence_label_never_reaches_gate(self):
        """
        Labels below promotion threshold must be blocked before the Reality Gate.
        """
        rec = LabelRecord(
            label_id="int-002",
            category=LabelCategory.VALID,
            confidence=0.50,  # below promotion threshold
            source="council",
            content="low-conf-proposal",
        )
        validator = LabelValidator()
        v = validator.validate_for_promotion(rec)
        self.assertFalse(v)  # stops here — never reaches the gate

    def test_non_promoted_label_blocked_at_gate(self):
        """
        Even a valid label without promotion approval must be blocked.
        """
        gate = GateFunction()
        decision = gate.evaluate(
            label_id="int-003",
            confidence=0.96,
            promoted=False,  # not promoted
            label_category="VALID",
            timestamp=1000.0,
        )
        self.assertEqual(decision.verdict, GateVerdict.NO)
        self.assertIn("NOT_PROMOTED", decision.rejection_reason)




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
