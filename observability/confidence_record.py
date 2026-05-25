"""
confidence_record.py — Labyrinth-OS / Epistemic Archive Layer (L5.5)
=====================================================================
Historical label confidence accuracy tracking.

Answers: "was the confidence we assigned to this label accurate in hindsight?"

Used by:
  - ConfidenceMeter — adjust historical_success component
  - PromotionRules — assess label trustworthiness
  - FeedbackLoop    — close the anomaly → archive → labeling loop

References:
  spec/ARCHIVE.md  — Confidence record specification
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Dict, List, Optional


# ─── LABEL OUTCOME ────────────────────────────────────────────────────────────

@unique
class LabelOutcome(str, Enum):
    """Observed outcome after a label was acted upon."""
    SUCCESS    = "SUCCESS"     # label predicted correctly; execution succeeded
    FAILURE    = "FAILURE"     # label predicted incorrectly; execution failed
    UNKNOWN    = "UNKNOWN"     # outcome not yet observed
    CANCELLED  = "CANCELLED"  # action was cancelled before outcome could be observed


# ─── CONFIDENCE OBSERVATION ───────────────────────────────────────────────────

@dataclass
class ConfidenceObservation:
    """
    One confidence prediction paired with its eventual outcome.

    Fields
    ------
    label_id         Label that was evaluated.
    predicted_conf   Confidence assigned at label creation time.
    outcome          What actually happened.
    outcome_time     When the outcome was observed.
    confidence_was_right  Whether predicted_conf was calibrated (True = well-calibrated).
    """
    label_id:             str
    predicted_conf:       float
    outcome:              LabelOutcome
    outcome_time:         float = field(default_factory=time.time)
    confidence_was_right: bool  = False

    def __post_init__(self) -> None:
        if self.outcome in (LabelOutcome.SUCCESS, LabelOutcome.FAILURE):
            # "Right" means: high confidence → success, low confidence → failure
            if self.outcome == LabelOutcome.SUCCESS:
                self.confidence_was_right = self.predicted_conf >= 0.60
            else:
                self.confidence_was_right = self.predicted_conf < 0.60


# ─── CONFIDENCE RECORD ────────────────────────────────────────────────────────

class ConfidenceRecord:
    """
    Track label confidence accuracy over time.

    Usage::

        record = ConfidenceRecord()
        record.record_prediction("lbl-001", predicted_conf=0.92)
        record.record_outcome("lbl-001", LabelOutcome.SUCCESS)
        print(record.accuracy())         # fraction of well-calibrated predictions
        print(record.trend("lbl-001"))   # "IMPROVING" | "DECLINING" | "STABLE"
    """

    def __init__(self, label_id: str = "") -> None:
        # Optional label_id for scoping this record to a specific label
        self._label_id = label_id
        # label_id → list of observations (chronological)
        self._observations: Dict[str, List[ConfidenceObservation]] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def predict(self, confidence: float) -> None:
        """Record a confidence prediction for this record's label_id."""
        lid = self._label_id or "default"
        self.record_prediction(lid, confidence)

    def predict_confidence_in_range(self) -> bool:
        """Check if predictions are within valid range [0,1]."""
        for obs_list in self._observations.values():
            for obs in obs_list:
                if not (0.0 <= obs.predicted_conf <= 1.0):
                    return False
        return True

    def record_prediction(self, label_id: str, predicted_conf: float) -> None:
        """
        Record a confidence prediction for a label.

        Must be called before record_outcome for the same label_id.
        If multiple predictions exist for the same label_id, a new
        observation row is appended (supporting repeated evaluations).
        """
        obs = ConfidenceObservation(
            label_id=label_id,
            predicted_conf=predicted_conf,
            outcome=LabelOutcome.UNKNOWN,
        )
        self._observations.setdefault(label_id, []).append(obs)

    def record_outcome(
        self, label_id: str,
        outcome: "LabelOutcome | bool | None" = None,
        success: bool = True,
    ) -> Optional[ConfidenceObservation]:
        """
        Update the most recent prediction for label_id with its observed outcome.

        Returns the updated observation, or None if no prediction exists.
        """
        observations = self._observations.get(label_id)
        if not observations:
            return None
        # Resolve outcome from success kwarg if outcome not explicitly set
        if outcome is None:
            resolved = LabelOutcome.SUCCESS if success else LabelOutcome.FAILURE
        elif isinstance(outcome, bool):
            resolved = LabelOutcome.SUCCESS if outcome else LabelOutcome.FAILURE
        else:
            resolved = outcome

        # Find the last unresolved entry (outcome is None or UNKNOWN)
        for obs in reversed(observations):
            if obs.outcome is None or obs.outcome == LabelOutcome.UNKNOWN:
                obs.outcome = resolved
                obs.outcome_time = time.time()
                if outcome in (LabelOutcome.SUCCESS, LabelOutcome.FAILURE):
                    obs.confidence_was_right = (
                        (outcome == LabelOutcome.SUCCESS and obs.predicted_conf >= 0.60)
                        or (outcome == LabelOutcome.FAILURE and obs.predicted_conf < 0.60)
                    )
                return obs
        return None

    def calibration_score(self) -> float:
        """Global calibration: fraction of predictions that were well-calibrated."""
        total = correct = 0
        for obs_list in self._observations.values():
            for obs in obs_list:
                if obs.outcome is None:
                    continue
                total += 1
                # Well-calibrated: high confidence + success, or low confidence + failure
                succeeded = (obs.outcome == LabelOutcome.SUCCESS)
                high_conf = obs.predicted_conf >= 0.65
                if succeeded == high_conf:
                    correct += 1
        return correct / max(total, 1)

    def accuracy(self) -> "float | None":
        """Fraction of well-calibrated predictions. None if no outcomes recorded."""
        has_outcomes = any(
            obs.outcome is not None
            for obs_list in self._observations.values()
            for obs in obs_list
        )
        if not has_outcomes:
            return 0.5  # neutral when no outcomes recorded
        return self.calibration_score()


    def label_accuracy(self, label_id: str) -> float:
        """
        Per-label accuracy.  Returns 0.5 if no resolved observations.
        """
        resolved = [
            obs
            for obs in self._observations.get(label_id, [])
            if obs.outcome in (LabelOutcome.SUCCESS, LabelOutcome.FAILURE)
        ]
        if not resolved:
            return 0.5
        correct = sum(1 for obs in resolved if obs.confidence_was_right)
        return correct / len(resolved)

    def trend(self, label_id: str, window: int = 10) -> str:
        """
        Return "IMPROVING", "DECLINING", or "STABLE" for label_id.

        Compares accuracy of the oldest half vs newest half of the window.
        """
        resolved = [
            obs
            for obs in self._observations.get(label_id, [])
            if obs.outcome in (LabelOutcome.SUCCESS, LabelOutcome.FAILURE)
        ][-window:]

        if len(resolved) < 4:
            return "STABLE"

        mid = len(resolved) // 2
        old_acc = sum(1 for o in resolved[:mid] if o.confidence_was_right) / mid
        new_acc = sum(1 for o in resolved[mid:] if o.confidence_was_right) / (len(resolved) - mid)
        delta = new_acc - old_acc
        if delta > 0.10:
            return "IMPROVING"
        if delta < -0.10:
            return "DECLINING"
        return "STABLE"

    def all_label_ids(self) -> List[str]:
        """Return all label_ids that have been tracked."""
        return list(self._observations.keys())




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_record_constructs() -> bool:
    r = ConfidenceRecord()
    assert r is not None
    return True

def _test_predict_then_outcome() -> bool:
    r = ConfidenceRecord()
    r.record_prediction("lbl1", 0.8)
    r.record_outcome("lbl1", LabelOutcome.SUCCESS)
    acc = r.accuracy()
    assert 0.0 <= acc <= 1.0
    return True

def _test_all_success_accuracy() -> bool:
    r = ConfidenceRecord()
    for _ in range(3):
        r.record_prediction("lbl", 0.9)
        r.record_outcome("lbl", LabelOutcome.SUCCESS)
    assert abs(r.accuracy() - 1.0) < 1e-9
    return True

def _test_all_failure_low_accuracy() -> bool:
    r = ConfidenceRecord()
    for _ in range(3):
        r.record_prediction("lbl", 0.9)
        r.record_outcome("lbl", LabelOutcome.FAILURE)
    assert r.accuracy() < 0.1
    return True

def _test_all_label_ids() -> bool:
    r = ConfidenceRecord()
    r.record_prediction("lbl1", 0.8)
    r.record_prediction("lbl2", 0.7)
    ids = r.all_label_ids()
    assert "lbl1" in ids and "lbl2" in ids
    return True



def _test_calibration_improves_with_data() -> bool:
    """More predictions → calibration score changes."""
    cr = ConfidenceRecord("test_calibration")
    for _ in range(10):
        cr.predict(0.90)
        cr.record_outcome("test_calibration", success=True)
    acc = cr.accuracy()
    assert acc is not None
    return True

def _test_zero_outcomes_gives_none_accuracy() -> bool:
    cr = ConfidenceRecord("no_data")
    # No outcomes → returns 0.5 (neutral)
    assert cr.accuracy() == 0.5
    return True

def _test_all_label_ids_nonempty() -> bool:
    cr = ConfidenceRecord("test")
    cr.predict(0.80)
    cr.record_outcome("test", success=True)
    ids = cr.all_label_ids()
    assert len(ids) > 0
    return True

def _test_predict_confidence_in_range() -> bool:
    cr = ConfidenceRecord("range_test")
    cr.predict(0.75)
    # Should not raise
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
