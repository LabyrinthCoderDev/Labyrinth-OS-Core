"""test_domain_adapter_contracts.py — Domain adapter contracts: 5 domains."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from cgir_signal_algebra import SensorReadings, SignalAlgebra, Severity

def _r(tau,chi,drift,betti,conf):
    return SensorReadings(tau_escape=tau,chi_vector=[chi],drift_score=drift,
                          betti_1=betti,confidence=conf,source="domain",logical_time=1)

def _blocked(tau,chi,drift,betti,conf):
    return SignalAlgebra.severity(_r(tau,chi,drift,betti,conf)) in (Severity.CRITICAL,Severity.ERROR)

# AI Governance
def test_ai_healthy_passes(): assert not _blocked(0.88,0.08,0.04,0.01,0.92)
def test_ai_chi_collapse_blocks(): assert _blocked(0.85,0.42,0.05,0.01,0.80)
def test_ai_low_tau_blocks(): assert _blocked(0.60,0.12,0.05,0.01,0.85)
def test_ai_missing_logprobs_blocks():
    from cgir_guardian_bridge import evaluate as bridge_eval
    from guardian_slot import SlotDecision
    r = _r(0.88,0.10,0.04,0.01,0.35)
    assert bridge_eval(r,cbf_margin=0.5,action_id="ai",session_id="t").slot_result.decision != SlotDecision.EXECUTE

# Industrial CNC
def test_cnc_healthy_passes(): assert not _blocked(0.95,0.06,0.03,0.01,0.96)
def test_cnc_tool_wear_blocks(): assert _blocked(0.65,0.10,0.05,0.01,0.90)
def test_cnc_parameter_drift_blocks(): assert _blocked(0.90,0.10,0.15,0.01,0.90)
def test_cnc_multiple_faults_blocks(): assert _blocked(0.90,0.10,0.05,0.10,0.90)

# Medical
def test_med_clear_diagnosis_passes(): assert not _blocked(0.92,0.05,0.03,0.01,0.90)
def test_med_drug_conflict_blocks(): assert _blocked(0.88,0.45,0.05,0.01,0.85)
def test_med_protocol_deviation_blocks(): assert _blocked(0.88,0.08,0.18,0.01,0.85)
def test_med_uncertain_diagnosis_blocks(): assert _blocked(0.60,0.10,0.05,0.01,0.85)

# Financial
def test_fin_strong_signal_passes(): assert not _blocked(0.91,0.07,0.04,0.01,0.88)
def test_fin_concentration_blocks(): assert _blocked(0.85,0.43,0.05,0.01,0.85)
def test_fin_regime_shift_blocks(): assert _blocked(0.85,0.08,0.20,0.01,0.85)
def test_fin_weak_signal_blocks(): assert _blocked(0.60,0.10,0.04,0.01,0.85)

# Autonomous Vehicles
def test_av_safe_trajectory_passes(): assert not _blocked(0.96,0.04,0.03,0.01,0.95)
def test_av_safety_breach_blocks(): assert _blocked(0.65,0.08,0.04,0.01,0.92)
def test_av_sensor_disagree_blocks(): assert _blocked(0.92,0.45,0.04,0.01,0.88)
def test_av_adverse_weather_blocks(): assert _blocked(0.92,0.08,0.18,0.01,0.88)
def test_av_low_perception_blocks():
    from cgir_guardian_bridge import evaluate as bridge_eval
    from guardian_slot import SlotDecision
    r = _r(0.92,0.08,0.04,0.01,0.40)
    assert bridge_eval(r,cbf_margin=0.5,action_id="av",session_id="t").slot_result.decision != SlotDecision.EXECUTE

def run_tests():
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("test_") and callable(o)], key=lambda x:x[0])
    passed=failed=0; results=[]
    for name,fn in tests:
        try: fn(); passed+=1; results.append((name,"PASS",None))
        except Exception as e: failed+=1; results.append((name,"FAIL",str(e)[:200]))
    return passed, failed, results
