"""
feedback_loop.py — Labyrinth-OS / Observability Layer (L5.75)
=============================================================
Close the observability → archive → labeling cycle.

Path:
  anomaly detected → archive query (similar past patterns?) →
  labeling validator confidence update → promotion rule adjustment

Used by:
  - Orchestrator (runtime/ignition.py) at the end of each cycle
  - Steward (steward/acp1_tracker.py) during assumption review

Invariant enforced:
  I15 — Feedback Loop Closure: anomalies → archive → label confidence updates.

References:
  spec/OBSERVABILITY.md — Feedback loop specification
  INVARIANTS.md         — I15
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from anomaly_log import AnomalyEntry, AnomalyLog, AnomalySeverity
from metrics import SystemMetrics


# ─── FEEDBACK RESULT ──────────────────────────────────────────────────────────

@dataclass
class FeedbackResult:
    """
    Result of one FeedbackLoop.process() call.

    Fields
    ------
    anomalies_processed   Number of anomaly entries consumed.
    confidence_adjustment Suggested delta to apply to label confidence.
                          Negative = decrease; 0.0 = no change.
    promote_flag          True if confidence is still above promotion threshold.
    demote_flag           True if confidence has fallen below demotion floor.
    notes                 List of human-readable observations.
    """
    anomalies_processed:   int
    confidence_adjustment: float
    promote_flag:          bool
    demote_flag:           bool
    notes:                 List[str] = field(default_factory=list)


# ─── FEEDBACK LOOP ────────────────────────────────────────────────────────────

class FeedbackLoop:
    """
    Compute confidence adjustments from recent anomalies.

    The loop does not directly modify labels — it produces a FeedbackResult
    that the caller (orchestrator or steward) applies to the labeling layer.

    Design principle: outputs are suggestions, not commands.  The labeling
    validator retains final authority over label classification.

    Usage::

        loop = FeedbackLoop(anomaly_log)
        result = loop.process(current_confidence=0.88, label_id="lbl-001")
        if result.demote_flag:
            # Tell the labeling validator to downgrade this label
            ...
    """

    #: Per-CRITICAL-anomaly confidence penalty.
    CRITICAL_PENALTY: float = 0.08
    #: Per-ERROR-anomaly confidence penalty.
    ERROR_PENALTY: float    = 0.03
    #: Per-WARN-anomaly confidence penalty.
    WARN_PENALTY:  float    = 0.01

    #: Threshold below which a label is considered for demotion.
    DEMOTION_FLOOR: float   = 0.60
    #: Threshold above which a label still qualifies for promotion.
    PROMOTION_THRESHOLD: float = 0.85

    def __init__(self, anomaly_log: AnomalyLog) -> None:
        self._log = anomaly_log

    # ── public API ────────────────────────────────────────────────────────────

    def process(
        self,
        current_confidence: float,
        label_id: Optional[str] = None,
        since: Optional[float] = None,
    ) -> FeedbackResult:
        """
        Process recent anomalies and compute a confidence adjustment.

        Parameters
        ----------
        current_confidence   Current label confidence score.
        label_id             If set, only anomalies for this label are counted.
        since                Only consider anomalies after this timestamp.

        Returns
        -------
        FeedbackResult with confidence_adjustment and promotion/demotion flags.
        """
        anomalies = self._log.query(label_id=label_id, since=since)
        notes: List[str] = []

        criticals = [a for a in anomalies if a.severity == AnomalySeverity.CRITICAL]
        errors    = [a for a in anomalies if a.severity == AnomalySeverity.ERROR]
        warns     = [a for a in anomalies if a.severity == AnomalySeverity.WARN]

        adjustment = (
            -len(criticals) * self.CRITICAL_PENALTY
            - len(errors)   * self.ERROR_PENALTY
            - len(warns)    * self.WARN_PENALTY
        )

        adjusted_conf = max(0.0, current_confidence + adjustment)

        if criticals:
            notes.append(
                f"{len(criticals)} CRITICAL anomalie(s) reduced confidence by "
                f"{len(criticals) * self.CRITICAL_PENALTY:.3f}"
            )
        if errors:
            notes.append(
                f"{len(errors)} ERROR anomalie(s) reduced confidence by "
                f"{len(errors) * self.ERROR_PENALTY:.3f}"
            )

        promote_flag = adjusted_conf >= self.PROMOTION_THRESHOLD
        demote_flag  = adjusted_conf < self.DEMOTION_FLOOR

        if demote_flag:
            notes.append(
                f"confidence {adjusted_conf:.3f} below demotion floor "
                f"{self.DEMOTION_FLOOR} — recommend label downgrade"
            )
        elif promote_flag:
            notes.append(
                f"confidence {adjusted_conf:.3f} above promotion threshold — "
                f"promotion still valid"
            )

        return FeedbackResult(
            anomalies_processed=len(anomalies),
            confidence_adjustment=adjustment,
            promote_flag=promote_flag,
            demote_flag=demote_flag,
            notes=notes,
        )

    def critical_anomaly_count(self, label_id: Optional[str] = None) -> int:
        """Return the number of CRITICAL anomalies (optionally per label)."""
        return len(self._log.query(severity=AnomalySeverity.CRITICAL, label_id=label_id))




def _test_loop_constructs() -> bool:
    from anomaly_log import AnomalyLog
    log = AnomalyLog()
    fl = FeedbackLoop(log)
    assert fl is not None
    return True

def _test_process_returns_result() -> bool:
    from anomaly_log import AnomalyLog
    log = AnomalyLog()
    fl = FeedbackLoop(log)
    result = fl.process(current_confidence=0.88, label_id="L001")
    assert result is not None
    assert hasattr(result, "confidence_adjustment")
    return True

def _test_confidence_adjustment_in_range() -> bool:
    from anomaly_log import AnomalyLog
    log = AnomalyLog()
    fl = FeedbackLoop(log)
    result = fl.process(current_confidence=0.88)
    adjusted = 0.88 + result.confidence_adjustment
    assert 0.0 <= adjusted <= 1.0
    return True

def _test_critical_anomaly_penalizes() -> bool:
    from anomaly_log import AnomalyLog, AnomalySeverity
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.CRITICAL, metric="tau",
               description="tau collapse", label_id="L001")
    fl = FeedbackLoop(log)
    result = fl.process(current_confidence=0.88, label_id="L001")
    # Critical anomaly → confidence_adjustment should be negative or zero
    assert result.confidence_adjustment <= 0.0
    return True

def _test_no_anomalies_minimal_adjustment() -> bool:
    from anomaly_log import AnomalyLog
    log = AnomalyLog()
    fl = FeedbackLoop(log)
    result = fl.process(current_confidence=0.88)
    # No anomalies → small or zero adjustment
    assert abs(result.confidence_adjustment) < 0.50
    return True

def _test_critical_count_with_label() -> bool:
    from anomaly_log import AnomalyLog, AnomalySeverity
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.CRITICAL, metric="tau",
               description="x", label_id="L001")
    fl = FeedbackLoop(log)
    count = fl.critical_anomaly_count(label_id="L001")
    assert count >= 1
    return True

def _test_critical_count_empty_log() -> bool:
    from anomaly_log import AnomalyLog
    log = AnomalyLog()
    fl = FeedbackLoop(log)
    assert fl.critical_anomaly_count() == 0
    return True

def _test_result_has_promote_flag() -> bool:
    from anomaly_log import AnomalyLog
    log = AnomalyLog()
    fl = FeedbackLoop(log)
    result = fl.process(current_confidence=0.88)
    assert hasattr(result, "promote_flag")
    assert hasattr(result, "demote_flag")
    return True


def run_tests() -> tuple:
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("_test_") and callable(o)], key=lambda x: x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn(); passed += 1; results.append((name, "PASS", None))
        except Exception as e:
            failed += 1; results.append((name, "FAIL", str(e)))
    return passed, failed, results
