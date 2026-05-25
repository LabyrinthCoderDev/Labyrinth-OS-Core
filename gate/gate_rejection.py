"""
gate_rejection.py — Labyrinth-OS / Reality Gate (L10.5)
=======================================================
Log and escalate Reality Gate rejections.

Every NO decision at the Reality Gate is logged here with its reason.
If the rejection rate exceeds a threshold, an escalation alert is raised.

Used by:
  - GateFunction (consult after a NO decision)
  - FeedbackLoop (query recent rejections)
  - Archive (REJECTION entry written here)

References:
  spec/REALITY_GATE.md — Gate rejection specification
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import List, Optional


# ─── REJECTION REASONS ────────────────────────────────────────────────────────

@unique
class GateRejectionReason(str, Enum):
    CONFIDENCE_TOO_LOW  = "CONFIDENCE_TOO_LOW"
    NOT_PROMOTED        = "NOT_PROMOTED"
    POLICY_VIOLATION    = "POLICY_VIOLATION"
    UNREVIEWED          = "UNREVIEWED"
    INVALID_CATEGORY    = "INVALID_CATEGORY"
    BINDING_RULE_FAILED = "BINDING_RULE_FAILED"


# ─── GATE REJECTION ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GateRejection:
    """
    Immutable record of one Reality Gate rejection.

    Fields
    ------
    rejection_id   Sequential identifier.
    label_id       Label that was rejected.
    reason         GateRejectionReason.
    detail         Human-readable detail.
    confidence     Confidence at rejection time.
    timestamp      When the rejection occurred.
    """
    rejection_id: int
    label_id:     str
    reason:       GateRejectionReason
    detail:       str
    confidence:   Optional[float]
    timestamp:    float


# ─── GATE REJECTOR ────────────────────────────────────────────────────────────

class GateRejector:
    """
    Log Reality Gate rejections and escalate when rate exceeds threshold.

    Usage::

        rejector = GateRejector(escalation_threshold=5)
        rejector.reject(
            label_id="lbl-001",
            reason=GateRejectionReason.NOT_PROMOTED,
            detail="label was not approved by promotion pipeline",
            confidence=0.60,
        )
        if rejector.should_escalate():
            # alert steward
            ...
    """

    #: Default rejection rate trigger for escalation.
    DEFAULT_ESCALATION_THRESHOLD: int = 5

    def __init__(self, escalation_threshold: int = DEFAULT_ESCALATION_THRESHOLD) -> None:
        self._rejections: List[GateRejection] = []
        self._escalation_threshold = escalation_threshold

    # ── public API ────────────────────────────────────────────────────────────

    def reject(
        self,
        label_id: str,
        reason: GateRejectionReason,
        detail: str,
        confidence: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> GateRejection:
        """
        Log a Reality Gate rejection.

        Returns the immutable GateRejection record.
        """
        rejection = GateRejection(
            rejection_id=len(self._rejections) + 1,
            label_id=label_id,
            reason=reason,
            detail=detail,
            confidence=confidence,
            timestamp=timestamp or time.time(),
        )
        self._rejections.append(rejection)
        return rejection

    def query(
        self,
        *,
        reason: Optional[GateRejectionReason] = None,
        label_id: Optional[str] = None,
        since: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> List[GateRejection]:
        """Query rejection records with optional filters."""
        results = list(self._rejections)
        if reason is not None:
            results = [r for r in results if r.reason == reason]
        if label_id is not None:
            results = [r for r in results if r.label_id == label_id]
        if since is not None:
            results = [r for r in results if r.timestamp >= since]
        if limit is not None:
            results = results[-limit:]
        return results

    def count(self, reason: Optional[GateRejectionReason] = None) -> int:
        """Count rejections, optionally filtered by reason."""
        if reason is None:
            return len(self._rejections)
        return sum(1 for r in self._rejections if r.reason == reason)

    def should_escalate(self, window: Optional[float] = None) -> bool:
        """
        Return True if the rejection count exceeds the escalation threshold.

        If *window* is set (seconds), only consider rejections within that window.
        """
        if window is not None:
            since = time.time() - window
            count = len([r for r in self._rejections if r.timestamp >= since])
        else:
            count = len(self._rejections)
        return count >= self._escalation_threshold

    def rejection_rate(self, total_evaluated: int) -> float:
        """Rejection rate as a fraction of total evaluations."""
        if total_evaluated == 0:
            return 0.0
        return len(self._rejections) / total_evaluated




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_rejector_constructs() -> bool:
    gr = GateRejector(); assert gr.count() == 0; return True

def _test_reject_increments_count() -> bool:
    gr = GateRejector()
    gr.reject(label_id="lbl1",
               reason=GateRejectionReason.CONFIDENCE_TOO_LOW,
               detail="conf=0.3", confidence=0.3)
    assert gr.count() == 1; return True

def _test_query_by_reason() -> bool:
    gr = GateRejector()
    gr.reject("lbl1", GateRejectionReason.CONFIDENCE_TOO_LOW, "low", 0.3)
    gr.reject("lbl2", GateRejectionReason.NOT_PROMOTED, "not promoted", None)
    low = gr.query(reason=GateRejectionReason.CONFIDENCE_TOO_LOW)
    assert len(low) == 1; return True

def _test_rejection_rate() -> bool:
    gr = GateRejector()
    gr.reject("lbl1", GateRejectionReason.CONFIDENCE_TOO_LOW, "low", 0.3)
    rate = gr.rejection_rate(total_evaluated=10)
    assert abs(rate - 0.1) < 1e-9; return True

def _test_escalation_at_threshold() -> bool:
    gr = GateRejector(escalation_threshold=3)
    for i in range(3):
        gr.reject(f"lbl{i}", GateRejectionReason.CONFIDENCE_TOO_LOW, "low", 0.2)
    assert gr.should_escalate(); return True

def _test_reasons_exist() -> bool:
    assert GateRejectionReason.CONFIDENCE_TOO_LOW in GateRejectionReason
    assert GateRejectionReason.NOT_PROMOTED in GateRejectionReason; return True



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
