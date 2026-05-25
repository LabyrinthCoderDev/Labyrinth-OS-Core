"""
cgir_signal_algebra.py — Labyrinth-OS / CGIR Phase 2
=====================================================
Signal Algebra — Sensor Readings → CGIR SignalNode

Converts VECTOR sensor readings (drift_score, χ-vector, τ-escape,
betti_1, confidence) into a single CGIR SignalNode that can be bound
to a CGIR edge and evaluated by the Gate.

This is the bridge between L3 (VECTOR Sensor Fabric) and L10 (CGIR).

Rules (from INVARIANTS.md and guardian_slot.py constants):
  τ_floor   = 0.75   — minimum τ-escape ratio
  drift_th  = 0.12   — drift score threshold (guardian_slot)
  χ_warn    = 0.15   — χ-vector risk warn threshold (χ is risk: high = bad)
  χ_col     = 0.40   — χ-vector collapse threshold
  β₁_cap    = 0.045  — Betti-1 topological cap

Severity escalation (deterministic, no floating-point ambiguity):
  CRITICAL  — τ-escape < τ_floor   OR  any χ component ≥ χ_col
  ERROR     — drift_score ≥ drift_th OR betti_1 ≥ β₁_cap
  WARNING   — χ-vector mean ≥ χ_warn  OR  confidence < 0.50
  INFO      — all checks pass

Confidence:
  Synthesized from weighted sensor inputs.
  Clipped to [0.0, 1.0].
  No randomness. Same inputs → same output.

This module has no side effects, no state, and no I/O.
Pure function: sensor_readings → SignalNode.

References:
  guardian_slot.py     — constants τ_floor, drift_th, χ_warn, χ_col, β₁_cap
  ARCHITECTURE.md      — L3 VECTOR (read-only sensor fabric)
  INVARIANTS.md        — I4 exactly one SignalNode per cycle (Council enforces COUNCIL tag)
  labyrinth_inventory  — VECTOR sensor constants table
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from cgir_types import NodeType, Severity, SignalNode, TimeRange


# ─── CONSTANTS (from guardian_slot.py + labyrinth_inventory) ──────────────────

TAU_FLOOR   = 0.75    # τ-escape ratio floor — below this is CRITICAL
DRIFT_TH    = 0.12    # drift score threshold — above this is ERROR
CHI_WARN     = 0.15    # χ-vector warn threshold — χ mean ≥ this is WARNING (χ = risk, high = bad)
CHI_COL     = 0.40    # χ-vector collapse threshold — at or above is CRITICAL
BETA_1_CAP  = 0.045   # Betti-1 topological cap — at or above is ERROR


# ─── SENSOR READING INPUT ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class SensorReadings:
    """
    Snapshot of VECTOR sensor outputs for one decision cycle.

    tau_escape    — τ-escape ratio ∈ [0.0, 1.0]. Higher = more observable.
    drift_score   — coherence drift ∈ [0.0, 1.0]. Higher = more drift.
    chi_vector    — list of χ-vector components ∈ [0.0, 1.0] each.
                    Represents multi-dimensional coherence.
    betti_1       — topological loop count proxy ∈ [0.0, ∞).
    confidence    — source sensor's own confidence in these readings ∈ [0.0, 1.0].
    source        — identifier of the sensor that produced these readings.
    logical_time  — logical time of the reading (non-negative integer).
    """
    tau_escape:   float
    drift_score:  float
    chi_vector:   List[float]
    betti_1:      float
    confidence:   float
    source:       str
    logical_time: int

    def __post_init__(self) -> None:
        # Types are checked here because frozen=True prevents mutation.
        # We do NOT raise on out-of-range values — that is the algebra's job.
        if not isinstance(self.chi_vector, list):
            raise TypeError("chi_vector must be a list of floats")
        if not isinstance(self.logical_time, int) or self.logical_time < 0:
            raise ValueError("logical_time must be a non-negative integer")
        if not self.source:
            raise ValueError("source must be non-empty")


# ─── SIGNAL ALGEBRA ───────────────────────────────────────────────────────────

class SignalAlgebra:
    """
    Converts SensorReadings into a CGIR SignalNode.

    Methods:
        evaluate(readings, signal_id, valid_for) → SignalNode

    The SignalNode's emitted_by is "SIGNAL_ALGEBRA" — this is raw sensor
    synthesis, not Council approval. Council Resolver receives this signal,
    wraps it with watcher evidence, and re-emits as emitted_by="COUNCIL" (I4).

    All logic is deterministic: same readings → same SignalNode.
    """

    @staticmethod
    def severity(readings: SensorReadings) -> Severity:
        """
        Determine severity level from sensor readings.

        Priority (highest wins):
          1. CRITICAL: τ < τ_floor  OR  any χᵢ ≥ χ_col
          2. ERROR:    drift ≥ drift_th  OR  β₁ ≥ β₁_cap
          3. WARNING:  mean(χ) ≥ χ_warn  OR  confidence < 0.50
          4. INFO:     all checks pass
        """
        # CRITICAL checks
        if readings.tau_escape < TAU_FLOOR:
            return Severity.CRITICAL
        if readings.chi_vector:
            if any(x >= CHI_COL for x in readings.chi_vector):
                return Severity.CRITICAL
        # ERROR checks
        if readings.drift_score >= DRIFT_TH:
            return Severity.ERROR
        if readings.betti_1 >= BETA_1_CAP:
            return Severity.ERROR
        # WARNING checks
        if readings.chi_vector:
            chi_mean = sum(readings.chi_vector) / len(readings.chi_vector)
            if chi_mean >= CHI_WARN:
                return Severity.WARNING
        if readings.confidence < 0.50:
            return Severity.WARNING
        return Severity.INFO

    @staticmethod
    def synthesize_confidence(readings: SensorReadings) -> float:
        """
        Synthesize a single confidence value from sensor readings.

        Formula (weighted average, clipped to [0.0, 1.0]):
          base      = source sensor confidence
          tau_adj   = τ-escape normalized — reward high τ
          drift_adj = penalize high drift
          chi_adj   = reward high mean χ (if χ present)
          betti_adj = penalize high β₁

          confidence = clip(0.40*base + 0.25*tau_norm + 0.20*drift_norm
                            + 0.10*chi_norm + 0.05*betti_norm, 0.0, 1.0)

        All intermediate values are clamped before weighting.
        """
        base = max(0.0, min(1.0, readings.confidence))

        tau_norm   = max(0.0, min(1.0, readings.tau_escape))
        drift_norm = max(0.0, min(1.0, 1.0 - readings.drift_score))

        if readings.chi_vector:
            chi_mean = sum(readings.chi_vector) / len(readings.chi_vector)
            chi_norm = max(0.0, min(1.0, 1.0 - chi_mean))  # high chi = risk = lower confidence
        else:
            chi_norm = 0.5  # neutral when no chi readings

        betti_raw  = max(0.0, readings.betti_1)
        # β₁ = 0 → norm = 1.0 (good); β₁ = β₁_cap → norm = 0.0 (bad)
        betti_norm = max(0.0, min(1.0, 1.0 - betti_raw / max(BETA_1_CAP, 1e-9)))

        composite = (
            0.40 * base +
            0.25 * tau_norm +
            0.20 * drift_norm +
            0.10 * chi_norm +
            0.05 * betti_norm
        )
        return max(0.0, min(1.0, composite))

    @staticmethod
    def category(readings: SensorReadings) -> str:
        """
        Human-readable category label based on the dominant signal.
        Used for audit logging — not for gate decisions.
        """
        if readings.tau_escape < TAU_FLOOR:
            return "TAU_ESCAPE_LOW"
        if readings.chi_vector and any(x >= CHI_COL for x in readings.chi_vector):
            return "CHI_COLLAPSE"
        if readings.drift_score >= DRIFT_TH:
            return "DRIFT"
        if readings.betti_1 >= BETA_1_CAP:
            return "TOPO_BREACH"
        if readings.chi_vector:
            chi_mean = sum(readings.chi_vector) / len(readings.chi_vector)
            if chi_mean >= CHI_WARN and chi_mean < CHI_COL:
                return "CHI_ELEVATED"
        if readings.confidence < 0.50:
            return "LOW_CONFIDENCE"
        return "NOMINAL"

    @classmethod
    def evaluate(
        cls,
        readings: SensorReadings,
        signal_id: str,
        valid_for: Optional[TimeRange] = None,
    ) -> SignalNode:
        """
        Main entry point: convert SensorReadings → CGIR SignalNode.

        The returned SignalNode has:
          emitted_by = "SIGNAL_ALGEBRA"  (Council upgrades this to COUNCIL)
          source     = readings.source
          logical_time = readings.logical_time
          severity   = determined by severity() above
          confidence = synthesized by synthesize_confidence() above
          category   = determined by category() above
        """
        sev  = cls.severity(readings)
        conf = cls.synthesize_confidence(readings)
        cat  = cls.category(readings)

        return SignalNode(
            id=signal_id,
            node_type=NodeType.SIGNAL,
            logical_time=readings.logical_time,
            severity=sev,
            confidence=conf,
            category=cat,
            evidence_refs=[],       # filled by Council with actual node refs
            valid_for=valid_for,
            source=readings.source,
            emitted_by="SIGNAL_ALGEBRA",  # raw algebra output — Council wraps and approves
        )


# ─── MODULE-LEVEL CONVENIENCE ─────────────────────────────────────────────────

def evaluate(readings: SensorReadings,
             signal_id: str,
             valid_for: Optional[TimeRange] = None) -> SignalNode:
    """Convenience: evaluate(readings, signal_id) → SignalNode."""
    return SignalAlgebra.evaluate(readings, signal_id, valid_for)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _nominal_readings(**overrides) -> SensorReadings:
    """Baseline NOMINAL sensor readings — all checks pass."""
    defaults = dict(
        tau_escape=0.85,
        drift_score=0.05,
        chi_vector=[0.05, 0.08, 0.06],  # low = healthy in χ (risk metric)
        betti_1=0.01,
        confidence=0.90,
        source="VECTOR",
        logical_time=0,
    )
    defaults.update(overrides)
    return SensorReadings(**defaults)


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_nominal_is_info() -> bool:
    """Nominal readings produce INFO severity."""
    r = _nominal_readings()
    assert SignalAlgebra.severity(r) == Severity.INFO
    return True


def _test_tau_below_floor_is_critical() -> bool:
    """τ-escape below τ_floor → CRITICAL."""
    r = _nominal_readings(tau_escape=TAU_FLOOR - 0.01)
    assert SignalAlgebra.severity(r) == Severity.CRITICAL
    return True


def _test_tau_exactly_floor_is_not_critical() -> bool:
    """τ-escape exactly at τ_floor is not CRITICAL."""
    r = _nominal_readings(tau_escape=TAU_FLOOR)
    sev = SignalAlgebra.severity(r)
    assert sev != Severity.CRITICAL, f"Expected not CRITICAL, got {sev}"
    return True


def _test_chi_collapse_is_critical() -> bool:
    """Any χᵢ ≥ χ_col → CRITICAL."""
    r = _nominal_readings(chi_vector=[0.10, CHI_COL, 0.20])
    assert SignalAlgebra.severity(r) == Severity.CRITICAL
    return True


def _test_chi_just_below_collapse_not_critical() -> bool:
    """χᵢ just below χ_col is not CRITICAL from chi check."""
    r = _nominal_readings(chi_vector=[CHI_COL - 0.001])  # 0.399 — still WARNING-level
    sev = SignalAlgebra.severity(r)
    assert sev != Severity.CRITICAL
    return True


def _test_high_drift_is_error() -> bool:
    """drift_score ≥ drift_th → ERROR (when τ and χ are fine)."""
    r = _nominal_readings(drift_score=DRIFT_TH)
    assert SignalAlgebra.severity(r) == Severity.ERROR
    return True


def _test_betti_at_cap_is_error() -> bool:
    """betti_1 ≥ β₁_cap → ERROR."""
    r = _nominal_readings(betti_1=BETA_1_CAP)
    assert SignalAlgebra.severity(r) == Severity.ERROR
    return True


def _test_elevated_chi_mean_is_warning() -> bool:
    """χ mean ≥ χ_warn and < χ_col → WARNING (χ is risk: high = bad)."""
    r = _nominal_readings(chi_vector=[CHI_WARN + 0.05])  # 0.20 — elevated but not collapse
    assert SignalAlgebra.severity(r) == Severity.WARNING
    return True


def _test_low_confidence_is_warning() -> bool:
    """confidence < 0.50 → WARNING."""
    r = _nominal_readings(confidence=0.45)
    assert SignalAlgebra.severity(r) == Severity.WARNING
    return True


def _test_critical_beats_error() -> bool:
    """CRITICAL from τ overrides ERROR from drift."""
    r = _nominal_readings(tau_escape=0.50, drift_score=0.20)
    assert SignalAlgebra.severity(r) == Severity.CRITICAL
    return True


def _test_error_beats_warning() -> bool:
    """ERROR from drift overrides WARNING from chi."""
    r = _nominal_readings(drift_score=DRIFT_TH, chi_vector=[CHI_WARN - 0.05])
    assert SignalAlgebra.severity(r) == Severity.ERROR
    return True


def _test_nominal_confidence_in_range() -> bool:
    """Nominal readings produce confidence in (0.5, 1.0]."""
    r = _nominal_readings()
    c = SignalAlgebra.synthesize_confidence(r)
    assert 0.5 < c <= 1.0, f"confidence={c} out of expected range"
    return True


def _test_bad_readings_lower_confidence() -> bool:
    """Poor readings produce lower confidence than nominal."""
    good = _nominal_readings()
    bad  = _nominal_readings(tau_escape=0.50, drift_score=0.25, confidence=0.30)
    assert SignalAlgebra.synthesize_confidence(bad) < SignalAlgebra.synthesize_confidence(good)
    return True


def _test_confidence_clipped_to_unit_interval() -> bool:
    """Confidence is always in [0.0, 1.0] regardless of inputs."""
    for conf in [0.0, 0.5, 1.0, -0.5, 1.5]:
        r = _nominal_readings(confidence=conf)
        c = SignalAlgebra.synthesize_confidence(r)
        assert 0.0 <= c <= 1.0, f"Confidence {c} out of [0,1]"
    return True


def _test_empty_chi_vector_handled() -> bool:
    """Empty χ-vector is handled gracefully."""
    r = _nominal_readings(chi_vector=[])
    sev  = SignalAlgebra.severity(r)
    conf = SignalAlgebra.synthesize_confidence(r)
    assert sev in (Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL)
    assert 0.0 <= conf <= 1.0
    return True


def _test_evaluate_returns_signal_node() -> bool:
    """evaluate() returns a SignalNode."""
    r = _nominal_readings()
    sig = evaluate(r, "sig_test_001")
    assert isinstance(sig, SignalNode)
    return True


def _test_evaluate_sets_signal_algebra_emitter() -> bool:
    """evaluate() sets emitted_by='SIGNAL_ALGEBRA'. Council wraps and approves."""
    r = _nominal_readings()
    sig = evaluate(r, "sig_i4")
    assert sig.emitted_by == "SIGNAL_ALGEBRA"
    return True


def _test_evaluate_preserves_signal_id() -> bool:
    """evaluate() uses the given signal_id."""
    r = _nominal_readings()
    sig = evaluate(r, "my_signal_xyz")
    assert sig.id == "my_signal_xyz"
    return True


def _test_evaluate_preserves_source() -> bool:
    """evaluate() preserves the source from readings."""
    r = _nominal_readings(source="WATCHER_A")
    sig = evaluate(r, "sig_src")
    assert sig.source == "WATCHER_A"
    return True


def _test_evaluate_preserves_logical_time() -> bool:
    """evaluate() preserves logical_time from readings."""
    r = _nominal_readings(logical_time=42)
    sig = evaluate(r, "sig_t42")
    assert sig.logical_time == 42
    return True


def _test_evaluate_valid_for_set_correctly() -> bool:
    """evaluate() passes valid_for TimeRange to SignalNode."""
    from cgir_types import TimeRange
    r = _nominal_readings(logical_time=5)
    vf = TimeRange(start_time=5, end_time=10)
    sig = evaluate(r, "sig_vf", valid_for=vf)
    assert sig.valid_for is not None
    assert sig.valid_for.start_time == 5
    assert sig.valid_for.end_time == 10
    return True


def _test_same_inputs_same_output() -> bool:
    """Same readings → same SignalNode (deterministic)."""
    r = _nominal_readings()
    s1 = evaluate(r, "sig_det")
    s2 = evaluate(r, "sig_det")
    assert s1.severity == s2.severity
    assert s1.confidence == s2.confidence
    assert s1.category == s2.category
    return True


def _test_category_nominal() -> bool:
    """Nominal readings produce NOMINAL category."""
    r = _nominal_readings()
    assert SignalAlgebra.category(r) == "NOMINAL"
    return True


def _test_category_tau_escape_low() -> bool:
    """τ below floor → TAU_ESCAPE_LOW category."""
    r = _nominal_readings(tau_escape=0.50)
    assert SignalAlgebra.category(r) == "TAU_ESCAPE_LOW"
    return True


def _test_category_drift() -> bool:
    """High drift → DRIFT category."""
    r = _nominal_readings(drift_score=0.20)
    assert SignalAlgebra.category(r) == "DRIFT"
    return True


def _test_category_chi_collapse() -> bool:
    """χ collapse → CHI_COLLAPSE category."""
    r = _nominal_readings(chi_vector=[0.42])
    assert SignalAlgebra.category(r) == "CHI_COLLAPSE"
    return True


def _test_critical_signal_passes_validator() -> bool:
    """A CRITICAL SignalNode from evaluate() passes cgir_validator (when unbound)."""
    from cgir_types import Edge, Node
    from cgir_core import CGIRGraph
    from cgir_validator import validate

    r = _nominal_readings(tau_escape=0.40)
    sig = evaluate(r, "sig_crit_val")
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_signal(sig)  # unbound — not linked to an edge yet
    result = validate(g)
    assert result.valid is True, f"Unexpected errors: {[e.error_type for e in result.errors]}"
    return True


def _test_sensor_readings_rejects_empty_source() -> bool:
    """SensorReadings rejects empty source."""
    try:
        SensorReadings(
            tau_escape=0.9, drift_score=0.05, chi_vector=[0.8],
            betti_1=0.01, confidence=0.9, source="", logical_time=0,
        )
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass
    return True


def _test_sensor_readings_rejects_negative_time() -> bool:
    """SensorReadings rejects negative logical_time."""
    try:
        SensorReadings(
            tau_escape=0.9, drift_score=0.05, chi_vector=[0.8],
            betti_1=0.01, confidence=0.9, source="VECTOR", logical_time=-1,
        )
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass
    return True


# ─── TEST RUNNER ──────────────────────────────────────────────────────────────

def run_tests() -> tuple:
    tests = sorted(
        [(name, obj) for name, obj in globals().items()
         if name.startswith("_test_") and callable(obj)],
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


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import hashlib as _hl
    print("=" * 70)
    print("CGIR SIGNAL ALGEBRA — Labyrinth-OS Phase 2")
    print("=" * 70)

    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()

    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err:
            line += f"  → {err}"
        print(line)

    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")

    if failed > 0:
        print("\n  ✗ TESTS FAILED")
        raise SystemExit(1)

    # Demo
    print("\n── DEMO: sensor readings → SignalNode ──\n")
    cases = [
        ("NOMINAL",   dict(tau_escape=0.90, drift_score=0.03, chi_vector=[0.05, 0.08])),
        ("LOW_TAU",   dict(tau_escape=0.60, drift_score=0.05, chi_vector=[0.10])),
        ("HIGH_DRIFT",dict(tau_escape=0.80, drift_score=0.15, chi_vector=[0.20])),
        ("COLLAPSE",  dict(tau_escape=0.80, drift_score=0.05, chi_vector=[0.42])),
        ("WORST",     dict(tau_escape=0.30, drift_score=0.30, chi_vector=[0.45], betti_1=0.05)),
    ]
    for label, kw in cases:
        r = _nominal_readings(**kw)
        sig = evaluate(r, f"sig_{label.lower()}")
        print(f"  {label:12}  sev={sig.severity.value:8}  conf={sig.confidence:.3f}  cat={sig.category}")

    with open(__file__, "rb") as f:
        file_hash = _hl.sha256(f.read()).hexdigest()

    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {file_hash}")
    print(f"  File:    cgir_signal_algebra.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 2 Step 2: cgir_signal_algebra.py — COMPLETE")
    print(f"{'=' * 70}")
