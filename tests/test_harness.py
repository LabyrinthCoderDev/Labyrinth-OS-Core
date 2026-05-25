"""
test_harness.py — Labyrinth-OS / Promotion Pipeline (L6.5)
===========================================================
Pre-promotion test harness.

Before a candidate label is promoted, it must pass this harness.
The harness runs the candidate through simulated conditions and measures
coherence, risk, latency, cost, and compliance against configurable thresholds.

Used by:
  PromotionRules.evaluate() — via harness_passed flag
  AuditTrail.record()       — HarnessResult stored in the audit record

References:
  spec/PROMOTION.md — Test harness specification
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─── HARNESS THRESHOLDS ───────────────────────────────────────────────────────

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "min_coherence":        0.80,   # τ must be ≥ this
    "max_risk":             0.20,   # χ must be ≤ this
    "max_latency_ms":       5000.0, # must complete within 5 s
    "max_cost_units":       100.0,  # abstract cost budget
    "min_compliance_score": 0.90,   # policy compliance
}


# ─── HARNESS RESULT ───────────────────────────────────────────────────────────

@dataclass
class HarnessResult:
    """
    Result of one TestHarness.run() call.

    Fields
    ------
    label_id            Candidate label under test.
    passed              True if all checks passed.
    coherence           Measured τ score [0, 1].
    risk                Measured χ score [0, 1].
    latency_ms          Measured latency in milliseconds.
    cost_units          Measured cost in abstract units.
    compliance_score    Policy compliance score [0, 1].
    failures            List of threshold violations (empty on pass).
    elapsed_ms          Wall-clock time spent running the harness.
    timestamp           When the harness was run.
    """
    label_id:         str
    passed:           bool
    coherence:        float
    risk:             float
    latency_ms:       float
    cost_units:       float
    compliance_score: float
    failures:         List[str] = field(default_factory=list)
    elapsed_ms:       float     = 0.0
    timestamp:        float     = field(default_factory=time.time)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] label_id={self.label_id!r} "
            f"coherence={self.coherence:.3f} risk={self.risk:.3f} "
            f"latency={self.latency_ms:.1f}ms compliance={self.compliance_score:.3f}"
            + (f" | failures: {'; '.join(self.failures)}" if self.failures else "")
        )


# ─── TEST HARNESS ────────────────────────────────────────────────────────────

class TestHarness:
    """
    Run a candidate label through a simulated gauntlet before promotion.

    In production this harness would invoke shadow branches (L8) and real
    CGIR compilation passes.  In this scaffold it accepts externally-measured
    values and applies the threshold checks deterministically.

    Usage::

        harness = TestHarness()
        result = harness.run(
            label_id="lbl-001",
            coherence=0.88,
            risk=0.12,
            latency_ms=450.0,
            cost_units=20.0,
            compliance_score=0.95,
        )
        print(result.passed)   # True
        print(result.summary())
    """

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
    ) -> None:
        self._thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            self._thresholds.update(thresholds)

    # ── public API ────────────────────────────────────────────────────────────

    def run(
        self,
        label_id: str,
        coherence: float,
        risk: float,
        latency_ms: float,
        cost_units: float,
        compliance_score: float,
    ) -> HarnessResult:
        """
        Evaluate a candidate against all harness thresholds.

        Parameters
        ----------
        label_id          Candidate label identifier.
        coherence         τ-escape coherence ratio [0, 1].
        risk              χ risk score [0, 1].
        latency_ms        Processing latency in milliseconds.
        cost_units        Abstract cost budget consumed.
        compliance_score  Policy compliance score [0, 1].

        Returns
        -------
        HarnessResult — passed=True only if all thresholds are satisfied.
        """
        start = time.monotonic()
        failures: List[str] = []

        t = self._thresholds
        if coherence < t["min_coherence"]:
            failures.append(
                f"coherence {coherence:.3f} < min {t['min_coherence']:.3f}"
            )
        if risk > t["max_risk"]:
            failures.append(
                f"risk {risk:.3f} > max {t['max_risk']:.3f}"
            )
        if latency_ms > t["max_latency_ms"]:
            failures.append(
                f"latency {latency_ms:.1f}ms > max {t['max_latency_ms']:.1f}ms"
            )
        if cost_units > t["max_cost_units"]:
            failures.append(
                f"cost {cost_units:.1f} > max {t['max_cost_units']:.1f}"
            )
        if compliance_score < t["min_compliance_score"]:
            failures.append(
                f"compliance {compliance_score:.3f} < min {t['min_compliance_score']:.3f}"
            )

        elapsed_ms = (time.monotonic() - start) * 1000.0

        return HarnessResult(
            label_id=label_id,
            passed=len(failures) == 0,
            coherence=coherence,
            risk=risk,
            latency_ms=latency_ms,
            cost_units=cost_units,
            compliance_score=compliance_score,
            failures=failures,
            elapsed_ms=elapsed_ms,
        )

    def update_threshold(self, name: str, value: float) -> None:
        """Update a single threshold (used in tests or runtime reconfiguration)."""
        if name not in self._thresholds:
            raise KeyError(f"unknown threshold: {name!r}")
        self._thresholds[name] = value

    def current_thresholds(self) -> Dict[str, float]:
        """Return a copy of the current threshold configuration."""
        return dict(self._thresholds)


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_harness_constructs() -> bool:
    h = TestHarness()
    assert h is not None
    return True

def _test_clean_signal_passes() -> bool:
    h = TestHarness()
    result = h.run(
        label_id="lbl_001",
        coherence=0.90,
        risk=0.05,
        latency_ms=50.0,
        cost_units=1.0,
        compliance_score=0.95,
    )
    assert result.passed, f"Expected pass: {result.failures}"
    return True

def _test_high_risk_fails() -> bool:
    h = TestHarness()
    result = h.run(
        label_id="lbl_002",
        coherence=0.90,
        risk=0.80,
        latency_ms=50.0,
        cost_units=1.0,
        compliance_score=0.95,
    )
    assert not result.passed
    assert len(result.failures) > 0
    return True

def _test_low_coherence_fails() -> bool:
    h = TestHarness()
    result = h.run(
        label_id="lbl_003",
        coherence=0.10,
        risk=0.05,
        latency_ms=50.0,
        cost_units=1.0,
        compliance_score=0.95,
    )
    assert not result.passed
    return True

def _test_result_has_label_id() -> bool:
    h = TestHarness()
    result = h.run("my_label", 0.9, 0.05, 50.0, 1.0, 0.95)
    assert result.label_id == "my_label"
    return True

def _test_result_timestamp_set() -> bool:
    import time
    h = TestHarness()
    before = time.time()
    result = h.run("lbl", 0.9, 0.05, 50.0, 1.0, 0.95)
    assert result.timestamp >= before
    return True


def run_tests() -> tuple:
    tests = sorted(
        [(n, o) for n, o in globals().items()
         if n.startswith("_test_") and callable(o)],
        key=lambda x: x[0],
    )
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)))
    return passed, failed, results
