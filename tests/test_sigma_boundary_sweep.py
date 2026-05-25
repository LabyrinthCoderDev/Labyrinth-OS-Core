"""test_sigma_boundary_sweep.py — Sigma anchor boundary sweep."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from cgir_signal_algebra import SensorReadings, SignalAlgebra, Severity
from guardian_slot import GuardianSlot, GuardianSignal, SlotDecision
EPS = 1e-6

def _slot(): return GuardianSlot()
def _signal(tau=0.90,chi=0.10,drift=0.05,betti=0.01,conf=0.85,cbf=0.5):
    return GuardianSignal(tau_escape=tau,drift_score=drift,chi_vector=chi,
                          cbf_margin=cbf,betti_1=betti,confidence=conf)

def test_tau_exactly_at_floor_not_execute():
    assert _slot().evaluate(_signal(tau=0.75)).decision != SlotDecision.EXECUTE
def test_tau_just_below_floor_kills():
    assert _slot().evaluate(_signal(tau=0.75-EPS)).decision == SlotDecision.KILL
def test_tau_just_above_floor_not_killed():
    assert _slot().evaluate(_signal(tau=0.75+EPS)).decision != SlotDecision.KILL
def test_tau_nominal_safe_executes():
    assert _slot().evaluate(_signal(tau=0.95,chi=0.08,drift=0.03,betti=0.01,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_tau_zero_kills():
    assert _slot().evaluate(_signal(tau=0.0)).decision == SlotDecision.KILL
def test_chi_exactly_at_collapse_kills():
    assert _slot().evaluate(_signal(chi=0.40)).decision == SlotDecision.KILL
def test_chi_just_below_collapse_blocks():
    assert _slot().evaluate(_signal(chi=0.40-EPS)).decision in (SlotDecision.BLOCK, SlotDecision.KILL)
def test_chi_just_above_collapse_kills():
    assert _slot().evaluate(_signal(chi=0.40+EPS)).decision == SlotDecision.KILL
def test_chi_warn_threshold_boundary():
    assert _slot().evaluate(_signal(chi=0.15,tau=0.95,drift=0.02,betti=0.01,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_chi_below_warn_executes():
    assert _slot().evaluate(_signal(chi=0.10,tau=0.95,drift=0.02,betti=0.01,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_chi_one_kills():
    assert _slot().evaluate(_signal(chi=1.0)).decision == SlotDecision.KILL
def test_drift_exactly_at_threshold_executes():
    assert _slot().evaluate(_signal(drift=0.12,tau=0.95,chi=0.08,betti=0.01,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_drift_just_below_threshold_executes():
    assert _slot().evaluate(_signal(drift=0.12-EPS,tau=0.95,chi=0.08,betti=0.01,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_drift_just_above_threshold_blocks():
    assert _slot().evaluate(_signal(drift=0.12+EPS,tau=0.95,chi=0.08,betti=0.01,conf=0.90,cbf=0.8)).decision != SlotDecision.EXECUTE
def test_betti_exactly_at_cap_executes():
    assert _slot().evaluate(_signal(betti=0.045,tau=0.95,chi=0.08,drift=0.02,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_betti_just_below_cap_executes():
    assert _slot().evaluate(_signal(betti=0.045-EPS,tau=0.95,chi=0.08,drift=0.02,conf=0.90,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_confidence_at_low_boundary_executes():
    assert _slot().evaluate(_signal(conf=0.65,tau=0.95,chi=0.08,drift=0.02,betti=0.01,cbf=0.8)).decision == SlotDecision.EXECUTE
def test_confidence_just_below_floor_blocks():
    assert _slot().evaluate(_signal(conf=0.65-EPS,tau=0.95,chi=0.08,drift=0.02,betti=0.01,cbf=0.8)).decision != SlotDecision.EXECUTE
def test_confidence_zero_blocks():
    assert _slot().evaluate(_signal(conf=0.0,tau=0.95,chi=0.08,drift=0.02,betti=0.01,cbf=0.8)).decision != SlotDecision.EXECUTE
def test_signal_algebra_tau_critical():
    r = SensorReadings(tau_escape=0.70,chi_vector=[0.10],drift_score=0.05,betti_1=0.01,confidence=0.85,source="sweep",logical_time=1)
    assert SignalAlgebra.severity(r) == Severity.CRITICAL
def test_signal_algebra_chi_critical():
    r = SensorReadings(tau_escape=0.90,chi_vector=[0.41],drift_score=0.05,betti_1=0.01,confidence=0.85,source="sweep",logical_time=1)
    assert SignalAlgebra.severity(r) == Severity.CRITICAL
def test_signal_algebra_drift_error():
    r = SensorReadings(tau_escape=0.90,chi_vector=[0.10],drift_score=0.13,betti_1=0.01,confidence=0.85,source="sweep",logical_time=1)
    assert SignalAlgebra.severity(r) == Severity.ERROR
def test_signal_algebra_nominal_info():
    r = SensorReadings(tau_escape=0.95,chi_vector=[0.08],drift_score=0.04,betti_1=0.01,confidence=0.90,source="sweep",logical_time=1)
    assert SignalAlgebra.severity(r) == Severity.INFO

def run_tests():
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("test_") and callable(o)], key=lambda x:x[0])
    passed=failed=0; results=[]
    for name,fn in tests:
        try: fn(); passed+=1; results.append((name,"PASS",None))
        except Exception as e: failed+=1; results.append((name,"FAIL",str(e)[:200]))
    return passed, failed, results
