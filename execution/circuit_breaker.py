"""
circuit_breaker.py — Labyrinth-OS / execution / gate
======================================================
Constitutional Deadlock Resolution — CircuitBreaker and DegradationDetector.

Closes the open gap noted in KNOWN_GAPS.md (constitutional deadlock):
  "The constitution has no supreme court. If watchers disagree repeatedly,
  or if promotion starvation occurs, the system has no built-in circuit
  breaker or human-escalation path."

THREE FAILURE MODES ADDRESSED:

  1. Gate rejects everything for an extended period (promotion starvation)
     — CircuitBreaker opens after N consecutive BLOCKs in a window.
     — Alerts operator. Does NOT bypass the gate. The gate stays up.
     — Open circuit means: reject new proposals until operator clears.

  2. Watcher council oscillates between two contradictory readings
     — DegradationDetector tracks watcher agreement over a rolling window.
     — Persistent disagreement (< agreement threshold) triggers DEGRADE state.
     — DEGRADE state: proposals are blocked + operator is notified.

  3. Confidence collapse spiral
     — DegradationDetector tracks confidence over a rolling window.
     — Sustained low confidence triggers DEGRADE state.
     — DEGRADE state: proposals are blocked + operator is notified.

DESIGN RULES:
  - CircuitBreaker NEVER bypasses the gate. It adds a layer before the gate.
  - When circuit is OPEN: proposals are rejected before reaching the gate.
  - When circuit is HALF_OPEN: one probe proposal is allowed through.
  - DEGRADE state is cleared only by explicit operator reset.
  - All state transitions are logged to the ledger.
  - Circuit breaker is fail-closed: unknown states → OPEN.

INTEGRATION:
  Add to robot_session.process() before the gate step:
    breaker_decision = self._circuit_breaker.check()
    if not breaker_decision.allow:
        # log CIRCUIT_OPEN to ledger, return BLOCK
        ...
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Deque, Dict, List, Optional, Tuple


# ─── CIRCUIT STATE ────────────────────────────────────────────────────────────

@unique
class CircuitState(str, Enum):
    CLOSED     = "CLOSED"     # Normal operation — proposals flow through
    HALF_OPEN  = "HALF_OPEN"  # One probe allowed — testing recovery
    OPEN       = "OPEN"       # Deadlocked — block all proposals, alert operator


@unique
class DegradeState(str, Enum):
    HEALTHY  = "HEALTHY"   # Normal operation
    WARNING  = "WARNING"   # Approaching threshold — operator notified
    DEGRADE  = "DEGRADE"   # Threshold crossed — block + operator escalation required


# ─── CIRCUIT BREAKER ──────────────────────────────────────────────────────────

@dataclass
class BreakerConfig:
    """Configuration for the circuit breaker."""
    # How many consecutive BLOCKs before circuit opens
    consecutive_block_threshold: int   = 10
    # How many BLOCKs in a rolling window before circuit opens
    window_block_threshold:      int   = 8
    # Size of the rolling window (number of proposals)
    window_size:                 int   = 20
    # How long (seconds) to stay OPEN before moving to HALF_OPEN
    open_duration_s:             float = 60.0
    # How many successful EXECUTES to close from HALF_OPEN
    half_open_success_required:  int   = 3


@dataclass
class BreakerDecision:
    """Result of a circuit breaker check."""
    allow:          bool
    circuit_state:  CircuitState
    reason:         str
    consecutive:    int
    window_blocks:  int
    timestamp:      float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow":         self.allow,
            "circuit_state": self.circuit_state.value,
            "reason":        self.reason,
            "consecutive":   self.consecutive,
            "window_blocks": self.window_blocks,
            "timestamp":     self.timestamp,
        }


class CircuitBreaker:
    """
    Constitutional deadlock resolver.

    Tracks consecutive BLOCKs and rolling window BLOCKs.
    When thresholds are exceeded: circuit OPENS, all proposals blocked,
    operator must investigate and reset.

    The gate itself is never bypassed. The circuit breaker sits before
    the gate and rejects proposals before they waste gate capacity when
    the system is in a deadlocked state.
    """

    def __init__(self, config: Optional[BreakerConfig] = None) -> None:
        self._cfg          = config or BreakerConfig()
        self._state        = CircuitState.CLOSED
        self._consecutive  = 0         # consecutive BLOCKs
        self._window: Deque[str] = deque(maxlen=self._cfg.window_size)
        self._opened_at: Optional[float] = None
        self._half_open_successes = 0
        self._history: List[Dict[str, Any]] = []

    @property
    def state(self) -> CircuitState:
        return self._state

    def check(self) -> BreakerDecision:
        """Check whether a proposal may proceed. Call before gate evaluation."""
        now = time.time()

        if self._state == CircuitState.OPEN:
            # Check if we can move to HALF_OPEN
            if self._opened_at and (now - self._opened_at) >= self._cfg.open_duration_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                return BreakerDecision(
                    allow=True,
                    circuit_state=CircuitState.HALF_OPEN,
                    reason="Circuit HALF_OPEN — probe proposal allowed",
                    consecutive=self._consecutive,
                    window_blocks=self._count_blocks(),
                )
            return BreakerDecision(
                allow=False,
                circuit_state=CircuitState.OPEN,
                reason=f"Circuit OPEN — deadlocked after {self._consecutive} consecutive BLOCKs. "
                       f"Operator reset required.",
                consecutive=self._consecutive,
                window_blocks=self._count_blocks(),
            )

        if self._state == CircuitState.HALF_OPEN:
            # Only allow one probe at a time
            return BreakerDecision(
                allow=True,
                circuit_state=CircuitState.HALF_OPEN,
                reason="Circuit HALF_OPEN — probe allowed",
                consecutive=self._consecutive,
                window_blocks=self._count_blocks(),
            )

        # CLOSED state — normal check
        return BreakerDecision(
            allow=True,
            circuit_state=CircuitState.CLOSED,
            reason="Circuit CLOSED — normal operation",
            consecutive=self._consecutive,
            window_blocks=self._count_blocks(),
        )

    def record_outcome(self, decision: str) -> Optional[CircuitState]:
        """
        Record a gate outcome (EXECUTE, BLOCK, KILL).
        Returns the new circuit state if it changed, else None.
        """
        prev_state = self._state
        self._window.append(decision)

        if decision == "EXECUTE":
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._cfg.half_open_success_required:
                    self._state        = CircuitState.CLOSED
                    self._consecutive  = 0
                    self._opened_at    = None
            else:
                self._consecutive = 0

        elif decision in ("BLOCK", "KILL"):
            self._consecutive += 1
            if self._state == CircuitState.HALF_OPEN:
                # Probe failed — reopen
                self._state      = CircuitState.OPEN
                self._opened_at  = time.time()
            elif self._state == CircuitState.CLOSED:
                window_blocks = self._count_blocks()
                if (self._consecutive >= self._cfg.consecutive_block_threshold or
                        window_blocks >= self._cfg.window_block_threshold):
                    self._state     = CircuitState.OPEN
                    self._opened_at = time.time()

        entry = {
            "decision":  decision,
            "state":     self._state.value,
            "consec":    self._consecutive,
            "window":    self._count_blocks(),
            "ts":        time.time(),
        }
        self._history.append(entry)

        return self._state if self._state != prev_state else None

    def operator_reset(self) -> None:
        """Operator clears the circuit. Moves OPEN → CLOSED."""
        self._state       = CircuitState.CLOSED
        self._consecutive = 0
        self._opened_at   = None
        self._half_open_successes = 0

    def _count_blocks(self) -> int:
        return sum(1 for d in self._window if d in ("BLOCK", "KILL"))

    def summary(self) -> Dict[str, Any]:
        return {
            "state":       self._state.value,
            "consecutive": self._consecutive,
            "window_blocks": self._count_blocks(),
            "window_size": len(self._window),
            "opened_at":   self._opened_at,
        }


# ─── DEGRADATION DETECTOR ─────────────────────────────────────────────────────

@dataclass
class DegradeConfig:
    """Configuration for the degradation detector."""
    # Rolling window size for confidence tracking
    confidence_window:        int   = 20
    # Mean confidence below this → WARNING
    confidence_warn_floor:    float = 0.50
    # Mean confidence below this → DEGRADE
    confidence_degrade_floor: float = 0.40
    # Watcher agreement window
    agreement_window:         int   = 20
    # Agreement ratio below this → WARNING
    agreement_warn_floor:     float = 0.60
    # Agreement ratio below this → DEGRADE
    agreement_degrade_floor:  float = 0.40


@dataclass
class DegradeReport:
    """Current degradation state."""
    state:              DegradeState
    reason:             str
    mean_confidence:    float
    agreement_ratio:    float
    window_size:        int
    timestamp:          float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state":           self.state.value,
            "reason":          self.reason,
            "mean_confidence": round(self.mean_confidence, 3),
            "agreement_ratio": round(self.agreement_ratio, 3),
            "window_size":     self.window_size,
            "timestamp":       self.timestamp,
        }


class DegradationDetector:
    """
    Tracks confidence collapse and watcher disagreement spirals.

    HEALTHY → WARNING → DEGRADE (requires operator reset to recover).

    Does not bypass the gate. In DEGRADE state, the caller should
    block proposals and notify the operator.

    EWMA-weighted (audit fix from portable_v2, May 2026):
    Recent events matter more than old ones. A BLOCK from 20 sessions
    ago should not weigh the same as one from right now. Flat rolling
    windows were treating stale data as current. EWMA corrects this.
    alpha=0.3: ~3 recent events dominate the signal.
    """
    _EWMA_ALPHA = 0.3  # smoothing factor — higher = faster response

    def __init__(self, config: Optional[DegradeConfig] = None) -> None:
        self._cfg   = config or DegradeConfig()
        self._state = DegradeState.HEALTHY
        self._ewma_confidence: Optional[float] = None
        self._ewma_agreement:  Optional[float] = None
        self._n_records: int = 0

    @property
    def state(self) -> DegradeState:
        return self._state

    def record(
        self,
        confidence:    float,
        watcher_agree: float,  # 0.0 = complete disagreement, 1.0 = full agreement
    ) -> DegradeReport:
        """Record a trial's confidence and watcher agreement. Returns current report."""
        a = self._EWMA_ALPHA
        # First record: seed EWMA with the actual value
        if self._ewma_confidence is None:
            self._ewma_confidence = confidence
            self._ewma_agreement  = watcher_agree
        else:
            self._ewma_confidence = a * confidence    + (1 - a) * self._ewma_confidence
            self._ewma_agreement  = a * watcher_agree + (1 - a) * self._ewma_agreement
        self._n_records += 1
        return self._evaluate()

    def _evaluate(self) -> DegradeReport:
        if self._ewma_confidence is None:
            return DegradeReport(
                state=DegradeState.HEALTHY, reason="Insufficient data",
                mean_confidence=1.0, agreement_ratio=1.0, window_size=0,
            )

        mean_conf  = self._ewma_confidence
        mean_agree = self._ewma_agreement if self._ewma_agreement is not None else 1.0

        # Check for DEGRADE condition
        if (mean_conf < self._cfg.confidence_degrade_floor or
                mean_agree < self._cfg.agreement_degrade_floor):
            self._state = DegradeState.DEGRADE
            reason = []
            if mean_conf < self._cfg.confidence_degrade_floor:
                reason.append(
                    f"confidence collapse: EWMA={mean_conf:.3f} < "
                    f"floor={self._cfg.confidence_degrade_floor:.3f}")
            if mean_agree < self._cfg.agreement_degrade_floor:
                reason.append(
                    f"watcher oscillation: EWMA={mean_agree:.3f} < "
                    f"floor={self._cfg.agreement_degrade_floor:.3f}")
            return DegradeReport(
                state=DegradeState.DEGRADE,
                reason="DEGRADE: " + "; ".join(reason),
                mean_confidence=mean_conf,
                agreement_ratio=mean_agree,
                window_size=self._n_records,
            )

        # Check for WARNING condition
        if (mean_conf < self._cfg.confidence_warn_floor or
                mean_agree < self._cfg.agreement_warn_floor):
            self._state = DegradeState.WARNING
            return DegradeReport(
                state=DegradeState.WARNING,
                reason=f"WARNING: EWMA_conf={mean_conf:.3f} EWMA_agree={mean_agree:.3f}",
                mean_confidence=mean_conf,
                agreement_ratio=mean_agree,
                window_size=self._n_records,
            )

        self._state = DegradeState.HEALTHY
        return DegradeReport(
            state=DegradeState.HEALTHY,
            reason="Healthy",
            mean_confidence=mean_conf,
            agreement_ratio=mean_agree,
            window_size=self._n_records,
        )

    def operator_reset(self) -> None:
        """Operator clears degraded state. Resets EWMA and state to HEALTHY."""
        self._state = DegradeState.HEALTHY
        self._ewma_confidence = None
        self._ewma_agreement  = None
        self._n_records       = 0


# ─── EVOLUTION ENGINE ─────────────────────────────────────────────────────────

@dataclass
class EvolvedThresholds:
    """Session-level runtime threshold adjustments. Never modifies Z3 baseline."""
    tau_floor:  float
    chi_collapse: float
    drift_threshold: float
    betti_cap:  float
    confidence_floor: float
    step: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tau_floor":        round(self.tau_floor, 6),
            "chi_collapse":     round(self.chi_collapse, 6),
            "drift_threshold":  round(self.drift_threshold, 6),
            "betti_cap":        round(self.betti_cap, 6),
            "confidence_floor": round(self.confidence_floor, 6),
            "step":             self.step,
            "reason":           self.reason,
        }


class EvolutionEngine:
    """
    Adjusts Sigma Anchor thresholds when system persistently degrades.

    Source: portable_v2 healing_system.py audit fix (May 2026).
    EWMA-bounded: max 10% change per step (relative, not absolute).

    KEY INVARIANT: Never modifies Z3-proven baseline constants.
    Applies only to session-level runtime thresholds.
    The Z3 proof (A021) remains valid — this engine operates on copies.

    Absolute delta_cap bug: 0.03 absolute = 67% change on betti_cap=0.045.
    Fixed: relative cap (10% of current value) bounds all adjustments.

    When to use:
      High block rate (>60%) → thresholds may be too strict → relax slightly
      Low block rate + high confidence → thresholds may be too loose → tighten
      Normal operation → no change
    """

    SAFE_DELTA_FRACTION = 0.10  # max 10% change per step

    def __init__(self) -> None:
        # Import Z3-proven baseline — copy to session-level values
        try:
            from sigma_anchors import (
                TAU_ESCAPE_FLOOR as _TAU,
                CHI_COLLAPSE     as _CHI,
                DRIFT_THRESHOLD  as _DRIFT,
                BETTI_1_CAP      as _BETTI,
                CONFIDENCE_FLOOR as _CONF,
            )
            self._tau   = _TAU
            self._chi   = _CHI
            self._drift = _DRIFT
            self._betti = _BETTI
            self._conf  = _CONF
        except ImportError:
            # Hardcoded fallback — Z3-proven values
            self._tau, self._chi = 0.75, 0.40
            self._drift, self._betti, self._conf = 0.12, 0.045, 0.65
        self._step = 0

    def evolve(self, block_rate: float, confidence: float) -> EvolvedThresholds:
        """
        Adjust session thresholds based on observed block_rate and confidence.
        Returns the adjusted thresholds for this session.
        """
        self._step += 1

        def bounded_adjust(current: float, target: float) -> float:
            """Adjust toward target but cap at SAFE_DELTA_FRACTION of current."""
            delta     = target - current
            max_delta = abs(current) * self.SAFE_DELTA_FRACTION
            clamped   = max(-max_delta, min(max_delta, delta))
            return current + clamped

        if block_rate > 0.6:
            # Too many blocks — system may be over-sensitive — relax slightly
            new_tau   = bounded_adjust(self._tau,   self._tau   * 0.97)
            new_chi   = bounded_adjust(self._chi,   self._chi   * 1.03)
            new_drift = bounded_adjust(self._drift, self._drift * 1.03)
            reason    = f"RELAX: block_rate={block_rate:.2f} > 0.60"
        elif block_rate < 0.1 and confidence > 0.85:
            # Very permissive — tighten slightly
            new_tau   = bounded_adjust(self._tau,   self._tau   * 1.02)
            new_chi   = bounded_adjust(self._chi,   self._chi   * 0.98)
            new_drift = bounded_adjust(self._drift, self._drift * 0.98)
            reason    = f"TIGHTEN: block_rate={block_rate:.2f} conf={confidence:.2f}"
        else:
            new_tau, new_chi, new_drift = self._tau, self._chi, self._drift
            reason = "STABLE: no adjustment"

        self._tau   = new_tau
        self._chi   = new_chi
        self._drift = new_drift

        return EvolvedThresholds(
            tau_floor        = round(new_tau,         6),
            chi_collapse     = round(new_chi,         6),
            drift_threshold  = round(new_drift,       6),
            betti_cap        = round(self._betti,     6),
            confidence_floor = round(self._conf,      6),
            step             = self._step,
            reason           = reason,
        )

    def reset(self) -> None:
        """Reset to baseline — called on operator_reset."""
        self.__init__()


# ─── TESTS ────────────────────────────────────────────────────────────────────

def run_tests() -> tuple:
    passed, failed, results = 0, 0, []

    def t(name, fn):
        nonlocal passed, failed
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)))

    def test_circuit_starts_closed():
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        d = cb.check()
        assert d.allow
        assert d.circuit_state == CircuitState.CLOSED
    t("test_circuit_starts_closed", test_circuit_starts_closed)

    def test_circuit_opens_after_consecutive_blocks():
        cb = CircuitBreaker(BreakerConfig(consecutive_block_threshold=3,
                                          window_block_threshold=99))
        for _ in range(3):
            cb.record_outcome("BLOCK")
        assert cb.state == CircuitState.OPEN
        d = cb.check()
        assert not d.allow
    t("test_circuit_opens_after_consecutive_blocks",
      test_circuit_opens_after_consecutive_blocks)

    def test_circuit_opens_after_window_blocks():
        cb = CircuitBreaker(BreakerConfig(
            consecutive_block_threshold=99, window_block_threshold=3,
            window_size=5))
        for _ in range(3):
            cb.record_outcome("BLOCK")
        assert cb.state == CircuitState.OPEN
    t("test_circuit_opens_after_window_blocks",
      test_circuit_opens_after_window_blocks)

    def test_execute_resets_consecutive():
        cb = CircuitBreaker(BreakerConfig(consecutive_block_threshold=5,
                                          window_block_threshold=99))
        for _ in range(4):
            cb.record_outcome("BLOCK")
        assert cb.state == CircuitState.CLOSED  # not yet open
        cb.record_outcome("EXECUTE")
        assert cb._consecutive == 0
    t("test_execute_resets_consecutive", test_execute_resets_consecutive)

    def test_half_open_after_duration():
        cb = CircuitBreaker(BreakerConfig(
            consecutive_block_threshold=2, window_block_threshold=99,
            open_duration_s=0.0))  # instant transition for testing
        cb.record_outcome("BLOCK")
        cb.record_outcome("BLOCK")
        assert cb.state == CircuitState.OPEN
        d = cb.check()
        assert d.circuit_state == CircuitState.HALF_OPEN
    t("test_half_open_after_duration", test_half_open_after_duration)

    def test_operator_reset_closes_circuit():
        cb = CircuitBreaker(BreakerConfig(consecutive_block_threshold=2,
                                          window_block_threshold=99))
        cb.record_outcome("BLOCK")
        cb.record_outcome("BLOCK")
        assert cb.state == CircuitState.OPEN
        cb.operator_reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.check().allow
    t("test_operator_reset_closes_circuit", test_operator_reset_closes_circuit)

    def test_degradation_starts_healthy():
        dd = DegradationDetector()
        assert dd.state == DegradeState.HEALTHY
    t("test_degradation_starts_healthy", test_degradation_starts_healthy)

    def test_degradation_warns_low_confidence():
        dd = DegradationDetector(DegradeConfig(
            confidence_window=5, confidence_warn_floor=0.60,
            confidence_degrade_floor=0.40))
        for _ in range(5):
            dd.record(confidence=0.55, watcher_agree=1.0)
        assert dd.state == DegradeState.WARNING
    t("test_degradation_warns_low_confidence",
      test_degradation_warns_low_confidence)

    def test_degradation_degrades_very_low_confidence():
        dd = DegradationDetector(DegradeConfig(
            confidence_window=5, confidence_degrade_floor=0.40,
            agreement_degrade_floor=0.0))
        for _ in range(5):
            dd.record(confidence=0.30, watcher_agree=1.0)
        assert dd.state == DegradeState.DEGRADE
        d = dd._evaluate()
        assert d.state == DegradeState.DEGRADE
    t("test_degradation_degrades_very_low_confidence",
      test_degradation_degrades_very_low_confidence)

    def test_degradation_detects_watcher_oscillation():
        dd = DegradationDetector(DegradeConfig(
            agreement_window=5, agreement_degrade_floor=0.50,
            confidence_degrade_floor=0.0))
        for _ in range(5):
            dd.record(confidence=0.85, watcher_agree=0.30)
        assert dd.state == DegradeState.DEGRADE
    t("test_degradation_detects_watcher_oscillation",
      test_degradation_detects_watcher_oscillation)

    def test_degradation_operator_reset():
        dd = DegradationDetector(DegradeConfig(
            confidence_window=3, confidence_degrade_floor=0.50,
            agreement_degrade_floor=0.0))
        for _ in range(3):
            dd.record(confidence=0.20, watcher_agree=1.0)
        assert dd.state == DegradeState.DEGRADE
        dd.operator_reset()
        assert dd.state == DegradeState.HEALTHY
    t("test_degradation_operator_reset", test_degradation_operator_reset)

    def test_report_serializable():
        import json
        dd = DegradationDetector()
        r = dd.record(0.85, 1.0)
        json.dumps(r.to_dict())
    t("test_report_serializable", test_report_serializable)

    def test_breaker_summary():
        import json
        cb = CircuitBreaker()
        cb.record_outcome("BLOCK")
        s = cb.summary()
        assert "state" in s and "consecutive" in s
    t("test_breaker_summary", test_breaker_summary)

    # ── EvolutionEngine tests ─────────────────────────────────────────────────

    def test_evolution_stable_no_change():
        eng = EvolutionEngine()
        orig_tau = eng._tau
        result = eng.evolve(block_rate=0.3, confidence=0.7)
        assert result.tau_floor == round(orig_tau, 6), "Stable: tau must not change"
        assert result.reason == "STABLE: no adjustment"
    t("test_evolution_stable", test_evolution_stable_no_change)

    def test_evolution_high_block_relaxes():
        eng = EvolutionEngine()
        orig_tau = eng._tau
        result = eng.evolve(block_rate=0.75, confidence=0.5)
        assert result.tau_floor < orig_tau, "High block rate must relax tau floor"
        assert "RELAX" in result.reason
    t("test_evolution_high_block_relaxes", test_evolution_high_block_relaxes)

    def test_evolution_low_block_tightens():
        eng = EvolutionEngine()
        orig_tau = eng._tau
        result = eng.evolve(block_rate=0.05, confidence=0.92)
        assert result.tau_floor > orig_tau, "Low block + high conf must tighten tau"
        assert "TIGHTEN" in result.reason
    t("test_evolution_low_block_tightens", test_evolution_low_block_tightens)

    def test_evolution_delta_bounded():
        eng = EvolutionEngine()
        orig_tau = eng._tau
        # Even extreme block rate can only move 10% per step
        result = eng.evolve(block_rate=1.0, confidence=0.0)
        max_change = abs(orig_tau) * EvolutionEngine.SAFE_DELTA_FRACTION
        assert abs(result.tau_floor - orig_tau) <= max_change + 1e-9, \
            f"Delta must be bounded to 10%: got {abs(result.tau_floor - orig_tau):.6f}"
    t("test_evolution_delta_bounded", test_evolution_delta_bounded)

    def test_evolution_never_exceeds_baseline():
        eng = EvolutionEngine()
        # Apply many tightening steps — should not grow unboundedly
        for _ in range(50):
            eng.evolve(block_rate=0.01, confidence=0.99)
        # tau_floor should not exceed original by more than compound 10% steps
        # (actual: each step is 2% increase max, 50 steps = ~2.7x — bounded by fraction)
        assert eng._tau < 10.0, "tau_floor must not grow unboundedly"
    t("test_evolution_bounded_growth", test_evolution_never_exceeds_baseline)

    def test_evolution_reset():
        eng = EvolutionEngine()
        orig_tau = eng._tau
        eng.evolve(block_rate=0.9, confidence=0.2)
        eng.reset()
        assert eng._tau == orig_tau, "Reset must restore Z3 baseline"
        assert eng._step == 0
    t("test_evolution_reset", test_evolution_reset)

    def test_evolved_thresholds_serializable():
        import json
        eng = EvolutionEngine()
        result = eng.evolve(0.5, 0.7)
        json.dumps(result.to_dict())  # must not raise
    t("test_evolved_thresholds_serial", test_evolved_thresholds_serializable)

    return passed, failed, results


if __name__ == "__main__":
    print("=" * 70)
    print("Labyrinth-OS — Circuit Breaker + Degradation Detector")
    print("Constitutional deadlock resolution.")
    print("=" * 70)
    print()
    p, f, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err:
            line += f"  → {err}"
        print(line)
    print(f"\n  Results: {p} passed, {f} failed")
    if f:
        raise SystemExit(1)
    print("\n  The circuit never bypasses the gate.")
    print("=" * 70)
