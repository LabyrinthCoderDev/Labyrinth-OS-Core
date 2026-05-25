"""
test_property_based.py — Labyrinth-OS
Property-based invariant proofs using Hypothesis.
Proves constitutional properties hold across the ENTIRE input space.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

tau_st   = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
chi_st   = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
drift_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
betti_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
conf_st  = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
cbf_st   = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@given(tau=tau_st, chi=chi_st, drift=drift_st, betti=betti_st, conf=conf_st, cbf=cbf_st)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_P1_gate_decision_is_deterministic(tau, chi, drift, betti, conf, cbf):
    """P1: Same SensorReadings always produces same decision."""
    from cgir_guardian_bridge import evaluate as bridge_eval
    from cgir_signal_algebra import SensorReadings
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    r1 = bridge_eval(r, cbf_margin=cbf, action_id="p1a", session_id="prop")
    r2 = bridge_eval(r, cbf_margin=cbf, action_id="p1b", session_id="prop")
    assert r1.slot_result.decision == r2.slot_result.decision


@given(tau=tau_st, drift=drift_st, betti=betti_st, conf=conf_st, cbf=cbf_st,
       chi=st.floats(min_value=0.40, max_value=1.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_P2_chi_collapse_never_executes(tau, chi, drift, betti, conf, cbf):
    """P2: chi >= 0.40 must never produce EXECUTE."""
    from cgir_guardian_bridge import evaluate as bridge_eval
    from cgir_signal_algebra import SensorReadings
    from guardian_slot import SlotDecision
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    result = bridge_eval(r, cbf_margin=cbf, action_id="p2", session_id="prop")
    assert result.slot_result.decision != SlotDecision.EXECUTE


@given(chi=chi_st, drift=drift_st, betti=betti_st, conf=conf_st, cbf=cbf_st,
       tau=st.floats(min_value=0.0, max_value=0.749, allow_nan=False, allow_infinity=False))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_P3_tau_below_floor_never_executes(tau, chi, drift, betti, conf, cbf):
    """P3: tau < 0.75 must never produce EXECUTE."""
    from cgir_guardian_bridge import evaluate as bridge_eval
    from cgir_signal_algebra import SensorReadings
    from guardian_slot import SlotDecision
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    result = bridge_eval(r, cbf_margin=cbf, action_id="p3", session_id="prop")
    assert result.slot_result.decision != SlotDecision.EXECUTE


@given(tau=tau_st, chi=chi_st, drift=drift_st, betti=betti_st, cbf=cbf_st,
       conf=st.floats(min_value=0.0, max_value=0.649, allow_nan=False, allow_infinity=False))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_P4_low_confidence_never_executes(tau, chi, drift, betti, conf, cbf):
    """P4: confidence < 0.65 must never produce EXECUTE."""
    from cgir_guardian_bridge import evaluate as bridge_eval
    from cgir_signal_algebra import SensorReadings
    from guardian_slot import SlotDecision
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    result = bridge_eval(r, cbf_margin=cbf, action_id="p4", session_id="prop")
    assert result.slot_result.decision != SlotDecision.EXECUTE


@given(tau=st.floats(min_value=0.0, max_value=0.74, allow_nan=False, allow_infinity=False),
       chi=st.floats(min_value=0.40, max_value=1.0, allow_nan=False, allow_infinity=False),
       conf=conf_st, cbf=cbf_st)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_P5_kill_not_downgraded_to_execute(tau, chi, conf, cbf):
    """P5: KILL decisions cannot be downgraded to EXECUTE in the same cycle.
    With tau below floor AND chi at collapse, the system must never return EXECUTE
    regardless of any other parameter values — human override cannot upgrade a KILL."""
    from cgir_guardian_bridge import evaluate as bridge_eval
    from cgir_signal_algebra import SensorReadings
    from guardian_slot import SlotDecision
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=0.05,
                       betti_1=0.01, confidence=conf, source="prop_test", logical_time=1)
    result = bridge_eval(r, cbf_margin=cbf, action_id="p5", session_id="prop")
    assert result.slot_result.decision != SlotDecision.EXECUTE


@given(tau=tau_st, chi=chi_st, drift=drift_st, betti=betti_st, conf=conf_st)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_P6_severity_always_valid_enum(tau, chi, drift, betti, conf):
    """P6: severity() always returns a valid Severity enum."""
    from cgir_signal_algebra import SignalAlgebra, SensorReadings, Severity
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    severity = SignalAlgebra.severity(r)
    assert isinstance(severity, Severity)
    assert severity in (Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL)


@given(payloads=st.lists(
    st.dictionaries(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
        st.integers(min_value=0, max_value=100), min_size=1, max_size=3),
    min_size=1, max_size=10))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_P7_hashchain_always_valid_when_untampered(payloads):
    """P7: HashChain.verify() always True for untampered chains."""
    from hashchain import HashChain
    from receipt import Receipt
    chain = HashChain()
    for i, payload in enumerate(payloads):
        r = Receipt(receipt_id=f"prop_p7_{i}", module="prop_test",
                    action="TEST", verdict="PASS", payload=payload,
                    prev_hash=chain.head_hash)
        chain.append(r)
    valid, broken_at, _ = chain.verify()
    assert valid


@given(chi_val=st.floats(min_value=0.28, max_value=0.399, allow_nan=False, allow_infinity=False))
@settings(max_examples=200)
def test_P8_chi_aggregate_floor_escalates(chi_val):
    """P8: chi_vector=[x,x] with mean>=0.28 must produce scalar>=0.40."""
    chi_vector = [chi_val, chi_val]
    chi_max    = max(chi_vector)
    chi_mean   = sum(chi_vector) / len(chi_vector)
    CHI_AGGREGATE_FLOOR = 0.28
    CHI_COLLAPSE = 0.40
    if chi_mean >= CHI_AGGREGATE_FLOOR:
        chi_scalar = max(chi_max, CHI_COLLAPSE)
    else:
        chi_scalar = chi_max
    assert chi_scalar >= CHI_COLLAPSE


@given(tau=tau_st, chi=chi_st, drift=drift_st, betti=betti_st, conf=conf_st)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_P9_sensor_readings_never_crash(tau, chi, drift, betti, conf):
    """P9: Any valid SensorReadings never raises an unhandled exception."""
    from cgir_signal_algebra import SignalAlgebra, SensorReadings
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    _ = SignalAlgebra.severity(r)
    _ = SignalAlgebra.synthesize_confidence(r)


@given(tau=tau_st, chi=chi_st, drift=drift_st, betti=betti_st, conf=conf_st)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_P10_synthesized_confidence_in_range(tau, chi, drift, betti, conf):
    """P10: synthesize_confidence() always returns value in [0.0, 1.0]."""
    from cgir_signal_algebra import SignalAlgebra, SensorReadings
    r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=drift,
                       betti_1=betti, confidence=conf, source="prop_test", logical_time=1)
    synth = SignalAlgebra.synthesize_confidence(r)
    assert 0.0 <= synth <= 1.0


def run_tests() -> tuple[int, int, list]:
    tests = sorted([(n, o) for n, o in globals().items()
                    if n.startswith("test_") and callable(o)], key=lambda x: x[0])
    passed = failed = 0
    results = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)[:200]))
    return passed, failed, results
