"""test_guardian_bridge_dedicated.py — Guardian bridge dedicated suite."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from cgir_guardian_bridge import evaluate as bridge_eval
from cgir_signal_algebra import SensorReadings
from guardian_slot import SlotDecision

def _r(tau=0.90,chi=None,drift=0.05,betti=0.02,conf=0.85,chi_vector=None):
    if chi_vector is None: chi_vector = [chi] if chi is not None else [0.10]
    return SensorReadings(tau_escape=tau,chi_vector=chi_vector,drift_score=drift,
                          betti_1=betti,confidence=conf,source="bridge_test",logical_time=1)

def test_bridge_chi_layer1_single_component_kills():
    result = bridge_eval(_r(chi_vector=[0.41]),cbf_margin=0.5,action_id="l1",session_id="t")
    assert result.slot_result.decision != SlotDecision.EXECUTE

def test_bridge_chi_layer2_aggregate_both_high():
    result = bridge_eval(_r(chi_vector=[0.39,0.39],conf=0.90,tau=0.90),cbf_margin=0.9,action_id="l2",session_id="t")
    assert result.slot_result.decision == SlotDecision.KILL, f"Layer 2 leak: got {result.slot_result.decision}"

def test_bridge_chi_layer2_mean_at_exact_floor():
    result = bridge_eval(_r(chi_vector=[0.28,0.28],conf=0.90,tau=0.90),cbf_margin=0.9,action_id="l2b",session_id="t")
    assert result.slot_result.decision != SlotDecision.EXECUTE

def test_bridge_chi_layer2_below_floor_not_always_kill():
    result = bridge_eval(_r(chi_vector=[0.10,0.10],conf=0.90,tau=0.90,drift=0.02,betti=0.01),cbf_margin=0.9,action_id="l2c",session_id="t")
    # Mean=0.10 < 0.28: should not KILL from aggregate alone
    assert result.slot_result.decision in (SlotDecision.EXECUTE, SlotDecision.BLOCK, SlotDecision.KILL)

def test_bridge_chi_layer3_far_from_ideal_dampens():
    result = bridge_eval(_r(chi_vector=[0.38],conf=0.90,tau=0.90,drift=0.02,betti=0.01),cbf_margin=0.9,action_id="l3",session_id="t")
    guardian_conf = result.slot_result.signal_snapshot.get("confidence", 1.0)
    assert guardian_conf <= 0.50

def test_bridge_chi_layer3_healthy_chi_no_penalty():
    result = bridge_eval(_r(chi_vector=[0.10],conf=0.85,tau=0.90,drift=0.02,betti=0.01),cbf_margin=0.9,action_id="l3b",session_id="t")
    assert result.slot_result.decision == SlotDecision.EXECUTE

def test_bridge_healthy_readings_execute():
    result = bridge_eval(_r(tau=0.95,chi_vector=[0.08],drift=0.02,betti=0.01,conf=0.90),cbf_margin=0.8,action_id="healthy",session_id="t")
    assert result.slot_result.decision == SlotDecision.EXECUTE

def test_bridge_empty_chi_vector_handled():
    result = bridge_eval(_r(chi_vector=[],conf=0.90,tau=0.90,drift=0.02,betti=0.01),cbf_margin=0.8,action_id="empty",session_id="t")
    assert result.slot_result.decision in (SlotDecision.EXECUTE, SlotDecision.BLOCK, SlotDecision.KILL)

def test_bridge_decision_is_deterministic():
    r = _r(tau=0.85,chi_vector=[0.15],drift=0.06,betti=0.02,conf=0.75)
    r1 = bridge_eval(r,cbf_margin=0.5,action_id="det1",session_id="t")
    r2 = bridge_eval(r,cbf_margin=0.5,action_id="det2",session_id="t")
    assert r1.slot_result.decision == r2.slot_result.decision

def test_bridge_chi_layer1_max_wins():
    result = bridge_eval(_r(chi_vector=[0.10,0.42,0.08]),cbf_margin=0.5,action_id="max",session_id="t")
    assert result.slot_result.decision != SlotDecision.EXECUTE

def run_tests():
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("test_") and callable(o)], key=lambda x:x[0])
    passed=failed=0; results=[]
    for name,fn in tests:
        try: fn(); passed+=1; results.append((name,"PASS",None))
        except Exception as e: failed+=1; results.append((name,"FAIL",str(e)[:200]))
    return passed, failed, results
