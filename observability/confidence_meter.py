"""
confidence_meter.py — Labyrinth-OS / Epistemic Labeling Layer (L3.5)
=====================================================================
Confidence scoring engine for the labeling layer.

Computes a composite confidence score from three independent signals:
  1. Sensor agreement  — how consistently do sensors agree on this label?
  2. Historical success — how often did this label pattern succeed in the past?
  3. Temporal consistency — has the confidence been stable recently?

Also tracks confidence decay over time and flags declining trends.

References:
  ARCHITECTURE.md  — L3.5 Labeling (confidence pipeline)
  spec/LABELING.md — Formal confidence model
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional


# ─── CONSTANTS ────────────────────────────────────────────────────────────────

#: Weights for the three confidence components (must sum to 1.0).
W_SENSOR_AGREEMENT:    float = 0.40
W_HISTORICAL_SUCCESS:  float = 0.35
W_TEMPORAL_CONSISTENCY: float = 0.25

#: Number of recent scores kept in the sliding window.
WINDOW_SIZE: int = 20

#: Per-second decay applied when compute_with_decay() is called.
DECAY_RATE: float = 0.001

#: Drop in rolling mean that triggers a declining-confidence flag.
DECLINE_THRESHOLD: float = 0.10


# ─── CONFIDENCE SAMPLE ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConfidenceSample:
    """A single confidence observation attached to a label_id."""
    label_id:        str
    score:           float      # composite in [0.0, 1.0]
    sensor_agreement: float     # component
    historical_success: float   # component
    temporal_consistency: float # component
    timestamp:       float = field(default_factory=time.time)


# ─── CONFIDENCE METER ─────────────────────────────────────────────────────────

class ConfidenceMeter:
    """
    Compute and track label confidence scores.

    Usage::

        meter = ConfidenceMeter()
        sample = meter.compute(
            label_id="lbl-001",
            sensor_agreement=0.90,
            historical_success=0.80,
            temporal_consistency=0.75,
        )
        print(sample.score)           # 0.836
        print(meter.is_declining())   # False
    """

    def __init__(self) -> None:
        self._window: Deque[ConfidenceSample] = deque(maxlen=WINDOW_SIZE)

    # ── core computation ──────────────────────────────────────────────────────

    def compute(
        self,
        label_id: str,
        sensor_agreement: float,
        historical_success: float,
        temporal_consistency: float,
    ) -> ConfidenceSample:
        """
        Compute a composite confidence score.

        Parameters
        ----------
        label_id              Identifier for the label being scored.
        sensor_agreement      [0,1] How much do sensors agree on this label?
        historical_success    [0,1] Historical success rate for this pattern.
        temporal_consistency  [0,1] Has confidence been stable recently?

        Returns
        -------
        ConfidenceSample with weighted composite score.
        """
        self._validate_component("sensor_agreement", sensor_agreement)
        self._validate_component("historical_success", historical_success)
        self._validate_component("temporal_consistency", temporal_consistency)

        score = (
            W_SENSOR_AGREEMENT * sensor_agreement
            + W_HISTORICAL_SUCCESS * historical_success
            + W_TEMPORAL_CONSISTENCY * temporal_consistency
        )
        score = min(1.0, max(0.0, score))  # clamp

        sample = ConfidenceSample(
            label_id=label_id,
            score=score,
            sensor_agreement=sensor_agreement,
            historical_success=historical_success,
            temporal_consistency=temporal_consistency,
        )
        self._window.append(sample)
        return sample

    def compute_with_decay(
        self,
        label_id: str,
        sensor_agreement: float,
        historical_success: float,
        temporal_consistency: float,
        last_computed_at: float,
    ) -> ConfidenceSample:
        """
        Compute confidence with temporal decay applied.

        The decay penalty is proportional to the time elapsed since
        last_computed_at, discouraging stale labels from retaining
        their old confidence.

        Parameters
        ----------
        last_computed_at  Unix timestamp of previous computation.
        """
        raw = self.compute(
            label_id, sensor_agreement, historical_success, temporal_consistency
        )
        elapsed = max(0.0, time.time() - last_computed_at)
        penalty = min(raw.score, DECAY_RATE * elapsed)
        decayed_score = max(0.0, raw.score - penalty)

        decayed = ConfidenceSample(
            label_id=label_id,
            score=decayed_score,
            sensor_agreement=raw.sensor_agreement,
            historical_success=raw.historical_success,
            temporal_consistency=raw.temporal_consistency,
            timestamp=raw.timestamp,
        )
        # Replace last sample with decayed version
        if self._window:
            self._window.pop()
        self._window.append(decayed)
        return decayed

    # ── trend analysis ────────────────────────────────────────────────────────

    def rolling_mean(self) -> Optional[float]:
        """Mean score across the sliding window.  None if window is empty."""
        if not self._window:
            return None
        return sum(s.score for s in self._window) / len(self._window)

    def is_declining(self) -> bool:
        """
        Return True if confidence has declined significantly.

        Compares the mean of the oldest half of the window to the mean
        of the newest half.  A drop ≥ DECLINE_THRESHOLD flags a decline.
        """
        samples = list(self._window)
        if len(samples) < 4:
            return False
        mid = len(samples) // 2
        old_mean = sum(s.score for s in samples[:mid]) / mid
        new_mean = sum(s.score for s in samples[mid:]) / (len(samples) - mid)
        return (old_mean - new_mean) >= DECLINE_THRESHOLD

    def recent_scores(self) -> List[float]:
        """Return a list of recent scores from the sliding window (oldest first)."""
        return [s.score for s in self._window]

    def reset(self) -> None:
        """Clear the sliding window."""
        self._window.clear()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_component(name: str, value: float) -> None:
        if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
            raise ValueError(f"{name} must be a float in [0.0, 1.0], got {value!r}")




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_meter_constructs() -> bool:
    m = ConfidenceMeter()
    assert m is not None
    return True

def _test_compute_returns_sample() -> bool:
    m = ConfidenceMeter()
    s = m.compute("lbl", sensor_agreement=0.8, historical_success=0.7, temporal_consistency=0.9)
    assert isinstance(s, ConfidenceSample)
    assert 0.0 <= s.score <= 1.0
    return True

def _test_all_zeros_low_score() -> bool:
    m = ConfidenceMeter()
    s = m.compute("lbl", sensor_agreement=0.0, historical_success=0.0, temporal_consistency=0.0)
    assert s.score < 0.2
    return True

def _test_all_ones_high_score() -> bool:
    m = ConfidenceMeter()
    s = m.compute("lbl", sensor_agreement=1.0, historical_success=1.0, temporal_consistency=1.0)
    assert s.score > 0.8
    return True

def _test_is_declining_returns_bool() -> bool:
    m = ConfidenceMeter()
    assert isinstance(m.is_declining(), bool)
    return True

def _test_rolling_mean() -> bool:
    m = ConfidenceMeter()
    m.compute("lbl", 0.8, 0.7, 0.9)
    mean = m.rolling_mean()
    assert isinstance(mean, float) and 0.0 <= mean <= 1.0
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
