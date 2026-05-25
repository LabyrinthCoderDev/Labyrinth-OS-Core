"""
drift_detector.py — Labyrinth-OS / Observability Layer (L5.75)
===============================================================
Detect system drift by comparing current metrics to a rolling baseline.

Drift beyond DRIFT_THRESHOLD triggers an alert that is forwarded to the
anomaly log and ultimately to the feedback loop.

References:
  ARCHITECTURE.md  — L5.75 Observability (drift detection)
  spec/OBSERVABILITY.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from metrics import SystemMetrics, DRIFT_THRESHOLD


# ─── DRIFT ALERT ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DriftAlert:
    """
    Emitted when drift exceeds DRIFT_THRESHOLD.

    Fields
    ------
    metric       Which metric drifted ("tau", "chi", "confidence", "drift").
    baseline     Baseline value the metric is compared against.
    current      Current observed value.
    delta        Absolute delta = |current - baseline|.
    severity     "ERROR" or "CRITICAL".
    timestamp    When the alert was generated.
    label_id     Associated label (if applicable).
    """
    metric:    str
    baseline:  float
    current:   float
    delta:     float
    severity:  str
    timestamp: float = field(default_factory=time.time)
    label_id:  Optional[str] = None

    @property
    def message(self) -> str:
        return (
            f"[{self.severity}] {self.metric} drifted by {self.delta:.4f} "
            f"(baseline={self.baseline:.4f}, current={self.current:.4f})"
        )


# ─── DRIFT DETECTOR ──────────────────────────────────────────────────────────

class DriftDetector:
    """
    Compare incoming SystemMetrics to a rolling baseline.

    Usage::

        detector = DriftDetector()
        detector.update_baseline(tau=0.85, chi=0.08, confidence=0.90)
        alerts = detector.check(metrics_snapshot)
        for alert in alerts:
            print(alert.message)
    """

    #: Number of recent snapshots used to compute the rolling baseline.
    BASELINE_WINDOW: int = 30

    def __init__(self) -> None:
        self._baseline: Optional[dict] = None
        self._window: List[SystemMetrics] = []
        self._alerts: List[DriftAlert] = []

    # ── baseline management ───────────────────────────────────────────────────

    def update_baseline(
        self,
        tau: float,
        chi: float,
        confidence: float,
        drift: float = 0.0,
    ) -> None:
        """Manually set the baseline (used at startup or after recalibration)."""
        self._baseline = {
            "tau": tau,
            "chi": chi,
            "confidence": confidence,
            "drift": drift,
        }

    def _compute_rolling_baseline(self) -> Optional[dict]:
        """Compute baseline from the sliding window of recent snapshots."""
        if len(self._window) < 5:
            return None
        window = self._window[-self.BASELINE_WINDOW:]
        return {
            "tau":        sum(m.tau for m in window) / len(window),
            "chi":        sum(m.chi for m in window) / len(window),
            "confidence": sum(m.confidence for m in window) / len(window),
            "drift":      sum(m.drift for m in window) / len(window),
        }

    # ── drift checking ────────────────────────────────────────────────────────

    def check(self, snapshot: SystemMetrics) -> List[DriftAlert]:
        """
        Compare *snapshot* to the current baseline.

        Returns a (possibly empty) list of DriftAlert objects.
        Also updates the internal sliding window.
        """
        self._window.append(snapshot)
        if len(self._window) > self.BASELINE_WINDOW * 2:
            self._window = self._window[-self.BASELINE_WINDOW:]

        # Prefer manual baseline; fall back to rolling
        baseline = self._baseline or self._compute_rolling_baseline()
        if baseline is None:
            return []

        alerts: List[DriftAlert] = []

        checks = {
            "tau":        (snapshot.tau,        baseline["tau"]),
            "chi":        (snapshot.chi,        baseline["chi"]),
            "confidence": (snapshot.confidence, baseline["confidence"]),
            "drift":      (snapshot.drift,      baseline["drift"]),
        }

        for metric, (current, base) in checks.items():
            delta = abs(current - base)
            if delta >= DRIFT_THRESHOLD:
                severity = "CRITICAL" if delta >= DRIFT_THRESHOLD * 2 else "ERROR"
                alert = DriftAlert(
                    metric=metric,
                    baseline=base,
                    current=current,
                    delta=delta,
                    severity=severity,
                    label_id=snapshot.label_id,
                )
                alerts.append(alert)
                self._alerts.append(alert)

        return alerts

    def recent_alerts(self, limit: int = 20) -> List[DriftAlert]:
        """Return the most recent drift alerts."""
        return self._alerts[-limit:]

    def alert_count(self) -> int:
        """Total number of drift alerts raised since initialization."""
        return len(self._alerts)

    def reset_baseline(self) -> None:
        """Clear the manually-set baseline; fall back to rolling."""
        self._baseline = None




def _test_detector_constructs() -> bool:
    dd = DriftDetector()
    assert dd.alert_count() == 0
    return True

def _test_no_alerts_on_nominal() -> bool:
    dd = DriftDetector()
    dd.update_baseline(tau=0.85, chi=0.08, confidence=0.88)
    snapshot = SystemMetrics(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    alerts = dd.check(snapshot)
    assert len(alerts) == 0
    return True

def _test_alert_on_tau_collapse() -> bool:
    dd = DriftDetector()
    dd.update_baseline(tau=0.85, chi=0.08, confidence=0.88)
    snapshot = SystemMetrics(tau=0.50, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    alerts = dd.check(snapshot)
    assert len(alerts) > 0
    return True

def _test_alert_on_confidence_drop() -> bool:
    dd = DriftDetector()
    dd.update_baseline(tau=0.85, chi=0.08, confidence=0.88)
    snapshot = SystemMetrics(tau=0.85, chi=0.08, drift=0.05, confidence=0.30, stage="gate")
    alerts = dd.check(snapshot)
    assert len(alerts) > 0
    return True

def _test_alert_count_increments() -> bool:
    dd = DriftDetector()
    dd.update_baseline(tau=0.85, chi=0.08, confidence=0.88)
    snapshot = SystemMetrics(tau=0.50, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    dd.check(snapshot)
    assert dd.alert_count() >= 1
    return True

def _test_recent_alerts_returns_list() -> bool:
    dd = DriftDetector()
    alerts = dd.recent_alerts()
    assert isinstance(alerts, list)
    return True

def _test_reset_baseline_clears() -> bool:
    dd = DriftDetector()
    dd.update_baseline(tau=0.85, chi=0.08, confidence=0.88)
    dd.reset_baseline()
    # After reset, no baseline — check doesn't raise
    snapshot = SystemMetrics(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    alerts = dd.check(snapshot)
    assert isinstance(alerts, list)
    return True

def _test_alert_message_nonempty() -> bool:
    dd = DriftDetector()
    dd.update_baseline(tau=0.85, chi=0.08, confidence=0.88)
    snapshot = SystemMetrics(tau=0.50, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    alerts = dd.check(snapshot)
    if alerts:
        assert len(alerts[0].message) > 0
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
