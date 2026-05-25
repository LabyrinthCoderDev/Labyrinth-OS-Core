"""
metrics.py — Labyrinth-OS / Observability Layer (L5.75)
=======================================================
Track τ (coherence), χ (risk), drift, and confidence metrics
at each stage of the epistemic pipeline.

Metrics are emitted at every labeling, promotion, and Reality Gate event.
They feed into the drift detector and anomaly log.

References:
  ARCHITECTURE.md  — L5.75 Observability
  spec/OBSERVABILITY.md — Formal metrics specification
  INVARIANTS.md    — I13 Observability completeness
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─── Σ ANCHOR CONSTANTS (mirrors execution/gate) ──────────────────────────────

# ─── Sigma Anchor constants — imported from single source of truth ───
try:
    import sys as _sys, os as _os
    _root = _os.path.normpath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
    if _root not in _sys.path: _sys.path.insert(0, _root)
    from sigma_anchors import (TAU_ESCAPE_FLOOR, CHI_WARN, CHI_COLLAPSE,
                                DRIFT_THRESHOLD, BETTI_1_CAP, CONFIDENCE_FLOOR)
except ImportError:
    TAU_ESCAPE_FLOOR = 0.75
    CHI_WARN = 0.15
    CHI_COLLAPSE = 0.40
    DRIFT_THRESHOLD = 0.12
    BETTI_1_CAP = 0.045
    CONFIDENCE_FLOOR = 0.65


# ─── SYSTEM METRICS SNAPSHOT ──────────────────────────────────────────────────

@dataclass
class SystemMetrics:
    """
    Snapshot of key system metrics at one point in time.

    Fields
    ------
    tau             τ-escape coherence ratio [0, 1].  Low = incoherent.
    chi             χ risk score [0, 1].  High = risky.
    drift           Coherence drift since last baseline.
    confidence      Current label confidence (if applicable).
    betti_1         β₁ topological complexity (optional).
    stage           Pipeline stage that emitted these metrics.
    label_id        Associated label (may be None).
    timestamp       Unix epoch float.
    """
    tau:        float
    chi:        float
    drift:      float
    confidence: float
    stage:      str
    betti_1:    float        = 0.0
    label_id:   Optional[str] = None
    timestamp:  float        = field(default_factory=time.time)

    # ── health assessment ──────────────────────────────────────────────────────

    @property
    def tau_critical(self) -> bool:
        return self.tau < TAU_ESCAPE_FLOOR

    @property
    def chi_critical(self) -> bool:
        return self.chi >= CHI_COLLAPSE

    @property
    def chi_warn(self) -> bool:
        return self.chi >= CHI_WARN

    @property
    def drift_error(self) -> bool:
        return self.drift >= DRIFT_THRESHOLD

    @property
    def betti_error(self) -> bool:
        return self.betti_1 >= BETTI_1_CAP

    @property
    def health(self) -> str:
        """
        Overall health classification.
        CRITICAL > ERROR > WARN > OK
        """
        if self.tau_critical or self.chi_critical:
            return "CRITICAL"
        if self.drift_error or self.betti_error:
            return "ERROR"
        if self.chi_warn:
            return "WARN"
        return "OK"


# ─── METRICS COLLECTOR ────────────────────────────────────────────────────────

class MetricsCollector:
    """
    Collect and store SystemMetrics snapshots.

    Thread-safe read; single-writer assumed (epistemic pipeline is sequential
    within a cycle).

    Usage::

        collector = MetricsCollector()
        m = collector.emit(tau=0.82, chi=0.10, drift=0.05,
                           confidence=0.90, stage="labeling")
        print(m.health)          # OK
        print(collector.latest)  # the snapshot just emitted
    """

    def __init__(self, max_history: int = 500) -> None:
        self._history: List[SystemMetrics] = []
        self._max_history = max_history

    # ── public API ────────────────────────────────────────────────────────────

    def emit(
        self,
        tau: float,
        chi: float,
        drift: float,
        confidence: float,
        stage: str,
        betti_1: float = 0.0,
        label_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> SystemMetrics:
        """
        Emit a metrics snapshot and add it to history.

        All values should be in [0.0, 1.0] except where noted.
        """
        m = SystemMetrics(
            tau=max(0.0, min(1.0, tau)),
            chi=max(0.0, min(1.0, chi)),
            drift=max(0.0, drift),
            confidence=max(0.0, min(1.0, confidence)),
            stage=stage,
            betti_1=max(0.0, betti_1),
            label_id=label_id,
            timestamp=timestamp or time.time(),
        )
        self._history.append(m)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return m

    @property
    def latest(self) -> Optional[SystemMetrics]:
        """Most recently emitted snapshot."""
        return self._history[-1] if self._history else None

    def history_for_stage(self, stage: str) -> List[SystemMetrics]:
        """Return all snapshots emitted for a specific pipeline stage."""
        return [m for m in self._history if m.stage == stage]

    def mean_confidence(self, stage: Optional[str] = None) -> Optional[float]:
        """Mean confidence across history (optionally filtered by stage)."""
        pool = self.history_for_stage(stage) if stage else self._history
        if not pool:
            return None
        return sum(m.confidence for m in pool) / len(pool)

    def mean_tau(self) -> Optional[float]:
        """Mean τ across all history."""
        if not self._history:
            return None
        return sum(m.tau for m in self._history) / len(self._history)

    def anomalous_snapshots(self) -> List[SystemMetrics]:
        """Return snapshots with health != OK."""
        return [m for m in self._history if m.health != "OK"]

    def clear(self) -> None:
        """Clear history (used in tests)."""
        self._history.clear()




def _test_system_metrics_constructs() -> bool:
    m = SystemMetrics(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    assert m.stage == "gate"
    assert m.tau == 0.85
    return True

def _test_health_nominal() -> bool:
    m = SystemMetrics(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    assert m.health == "OK"
    return True

def _test_health_critical_on_low_tau() -> bool:
    m = SystemMetrics(tau=0.60, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    assert m.health in ("CRITICAL", "ERROR", "WARN")
    return True

def _test_tau_critical_flag() -> bool:
    m = SystemMetrics(tau=0.60, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    assert m.tau_critical
    return True

def _test_chi_warn_flag() -> bool:
    m = SystemMetrics(tau=0.85, chi=0.20, drift=0.05, confidence=0.88, stage="gate")
    assert m.chi_warn
    return True

def _test_collector_emit_and_latest() -> bool:
    mc = MetricsCollector()
    mc.emit(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    assert mc.latest is not None
    assert mc.latest.stage == "gate"
    return True

def _test_collector_mean_confidence() -> bool:
    mc = MetricsCollector()
    mc.emit(tau=0.85, chi=0.08, drift=0.05, confidence=0.80, stage="gate")
    mc.emit(tau=0.85, chi=0.08, drift=0.05, confidence=0.90, stage="gate")
    mean = mc.mean_confidence()
    assert mean is not None
    assert abs(mean - 0.85) < 1e-6
    return True

def _test_collector_history_for_stage() -> bool:
    mc = MetricsCollector()
    mc.emit(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")
    mc.emit(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="labeling")
    gate_history = mc.history_for_stage("gate")
    assert len(gate_history) == 1
    return True

def _test_anomalous_snapshots_detected() -> bool:
    mc = MetricsCollector()
    mc.emit(tau=0.60, chi=0.08, drift=0.05, confidence=0.88, stage="gate")  # anomalous
    mc.emit(tau=0.85, chi=0.08, drift=0.05, confidence=0.88, stage="gate")  # normal
    anomalous = mc.anomalous_snapshots()
    assert len(anomalous) >= 1
    return True

def _test_empty_collector_returns_none() -> bool:
    mc = MetricsCollector()
    assert mc.latest is None
    assert mc.mean_confidence() is None
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
