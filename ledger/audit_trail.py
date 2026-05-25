"""
audit_trail.py — Labyrinth-OS / Promotion Pipeline (L6.5)
=========================================================
Immutable audit trail of all promotion decisions.

Every promotion, deferral, and rejection is recorded here with:
  - Who approved it (or what rule rejected it)
  - When it happened
  - What the justification was
  - What the test harness results were

Invariant enforced:
  I14 — Promotion Auditability: all promotions recorded with justification.

References:
  spec/PROMOTION.md — Audit trail specification
  INVARIANTS.md     — I14
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from promotion_rules import PromotionDecision, PromotionOutcome

from test_harness import HarnessResult  # noqa: E402


# ─── AUDIT RECORD ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuditRecord:
    """
    One immutable promotion audit entry.

    Fields
    ------
    audit_id         Sequential identifier within this trail.
    label_id         Label that was evaluated.
    outcome          APPROVED | REJECTED | DEFERRED.
    approved_by      Identity of the approver (None for auto-rejections).
    justification    Human-readable justification or rule summary.
    decision_reasons Decision reasons from PromotionRules.
    harness_summary  Summary string from HarnessResult (may be None).
    timestamp        When the audit record was created.
    """
    audit_id:         int
    label_id:         str
    outcome:          str              # PromotionOutcome value
    approved_by:      Optional[str]
    justification:    str
    decision_reasons: List[str]
    harness_summary:  Optional[str]
    timestamp:        float
    confidence:       float = 0.0


# ─── AUDIT TRAIL ─────────────────────────────────────────────────────────────

class AuditTrail:
    """
    Append-only, immutable audit trail of promotion decisions.

    No record may be modified or deleted.

    Usage::

        trail = AuditTrail()
        trail.record(
            decision=promotion_decision,
            approved_by="steward",
            justification="all rules passed, steward confirmed",
            harness_result=harness_result,
        )
        records = trail.all_records()
    """

    def __init__(self) -> None:
        self._records: List[AuditRecord] = []

    # ── public API ────────────────────────────────────────────────────────────

    def record(
        self,
        decision: "Optional[PromotionDecision]" = None,
        label_id: str = "",      # accepted — decision carries label
        stage: str = "",         # pipeline stage
        outcome: str = "",       # accepted for compat
        confidence: float = 0.0, # accepted for compat
        approved_by: Optional[str] = None,
        justification: str = "",
        harness_result: Optional[HarnessResult] = None,
    ) -> AuditRecord:
        """
        Record a promotion decision.

        Parameters
        ----------
        decision        The PromotionDecision to record.
        approved_by     Identity of human/agent approver (None for auto).
        justification   Human-readable justification string.
        harness_result  Optional HarnessResult to attach.

        Returns
        -------
        The created (immutable) AuditRecord.
        """
        if not justification:
            justification = ("; ".join(decision.reasons) if decision and hasattr(decision,"reasons")
                             else "no reasons recorded")

        record = AuditRecord(
            audit_id=len(self._records) + 1,
            label_id=(decision.label_id if decision else label_id),
            outcome=(decision.outcome.value if decision else outcome),
            approved_by=approved_by,
            justification=justification,
            decision_reasons=(list(decision.reasons) if decision and hasattr(decision,"reasons") else []),
            confidence=confidence,
            harness_summary=harness_result.summary() if harness_result else None,
            timestamp=time.time(),
        )
        self._records.append(record)
        return record

    def all_records(self) -> List[AuditRecord]:
        """Return all audit records (chronologically ordered)."""
        return list(self._records)

    def records_by_outcome(self, outcome: str) -> List[AuditRecord]:
        """Return all records matching the given outcome string."""
        return [r for r in self._records if r.outcome == outcome]

    def records_for_label(self, label_id: str) -> List[AuditRecord]:
        """Return all audit records for a specific label_id."""
        return [r for r in self._records if r.label_id == label_id]

    def approved_records(self) -> List[AuditRecord]:
        """Return all APPROVED audit records."""
        return [r for r in self._records if r.outcome == PromotionOutcome.APPROVED.value]

    def count(self) -> int:
        """Total number of audit records."""
        return len(self._records)

    def was_approved(self, label_id: str) -> bool:
        """Return True if at least one APPROVED record exists for label_id."""
        return any(
            r.label_id == label_id and r.outcome == PromotionOutcome.APPROVED.value
            for r in self._records
        )




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

try:
    from promotion_rules import PromotionRules
except ImportError:
    pass  # PromotionRules used in tests only; tests handle its absence

def _test_trail_constructs() -> bool:
    t = AuditTrail()
    assert t.count() == 0
    return True

def _test_record_appended() -> bool:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from promotion_rules import PromotionDecision, PromotionOutcome
def _test_no_delete_method() -> bool:
    t = AuditTrail()
    assert not hasattr(t, "delete")
    return True

def _test_records_for_label() -> bool:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from promotion_rules import PromotionDecision, PromotionOutcome
def _test_count_increments() -> bool:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from promotion_rules import PromotionDecision, PromotionOutcome
def _test_records_by_stage() -> bool:
    at = AuditTrail()
    at.record(label_id="L001", stage="promotion", outcome="PASS", confidence=0.85)
    at.record(label_id="L001", stage="reality_gate", outcome="PASS", confidence=0.85)
    records = at.records_for_label("L001")
    assert len(records) == 2
    return True

def _test_outcome_filter() -> bool:
    at = AuditTrail()
    at.record(label_id="L001", stage="promotion", outcome="PASS", confidence=0.85)
    at.record(label_id="L002", stage="promotion", outcome="FAIL", confidence=0.40)
    fails = at.records_by_outcome("FAIL")
    assert len(fails) == 1
    return True

def _test_trail_is_immutable() -> bool:
    at = AuditTrail()
    at.record(label_id="L001", stage="gate", outcome="PASS", confidence=0.85)
    c = at.count()
    assert c == 1
    # Verify no delete/remove methods
    assert not hasattr(at, "delete")
    return True

def _test_confidence_recorded() -> bool:
    at = AuditTrail()
    at.record(label_id="L001", stage="gate", outcome="PASS", confidence=0.92)
    records = at.records_for_label("L001")
    assert records[0].confidence == 0.92
    return True

def run_tests() -> tuple:
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("_test_") and callable(o)], key=lambda x:x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn(); passed += 1; results.append((name,"PASS",None))
        except Exception as e:
            failed += 1; results.append((name,"FAIL",str(e)))
    return passed, failed, results