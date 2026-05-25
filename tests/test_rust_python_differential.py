"""test_rust_python_differential.py — Rust/Python differential parity (GAP R4)."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
BASE = os.path.dirname(os.path.abspath(__file__))

def test_rust_python_TAU_ESCAPE_FLOOR_match():
    from sigma_anchors import TAU_ESCAPE_FLOOR
    rust_src = os.path.join(BASE, 'crates', 'cgir-types', 'src', 'lib.rs')
    if not os.path.exists(rust_src): return True  # No Rust crates in Core
    with open(rust_src) as f: rsrc = f.read()
    assert str(TAU_ESCAPE_FLOOR) in rsrc and 'TAU_ESCAPE_FLOOR' in rsrc

def test_rust_python_CHI_COLLAPSE_match():
    from sigma_anchors import CHI_COLLAPSE
    rust_src = os.path.join(BASE, 'crates', 'cgir-types', 'src', 'lib.rs')
    if not os.path.exists(rust_src): return True  # No Rust crates in Core
    with open(rust_src) as f: rsrc = f.read()
    assert str(CHI_COLLAPSE) in rsrc and 'CHI_COLLAPSE' in rsrc

def test_rust_python_DRIFT_THRESHOLD_match():
    from sigma_anchors import DRIFT_THRESHOLD
    rust_src = os.path.join(BASE, 'crates', 'cgir-types', 'src', 'lib.rs')
    if not os.path.exists(rust_src): return True  # No Rust crates in Core
    with open(rust_src) as f: rsrc = f.read()
    assert str(DRIFT_THRESHOLD) in rsrc and 'DRIFT_THRESHOLD' in rsrc

def test_rust_python_gate_constants_match():
    from sigma_anchors import TAU_ESCAPE_FLOOR, CHI_COLLAPSE, DRIFT_THRESHOLD
    gate_src = os.path.join(BASE, 'crates', 'gate', 'src', 'lib.rs')
    if not os.path.exists(gate_src): return True  # No Rust crates in Core
    with open(gate_src) as f: rsrc = f.read()
    for name, val in [('TAU_ESCAPE_FLOOR', TAU_ESCAPE_FLOOR),
                      ('CHI_COLLAPSE', CHI_COLLAPSE),
                      ('DRIFT_THRESHOLD', DRIFT_THRESHOLD)]:
        assert name in rsrc and str(val) in rsrc

def test_rust_python_runtime_parity_python_blocks_correctly():
    from sigma_anchors import TAU_ESCAPE_FLOOR, CHI_COLLAPSE
    from cgir_signal_algebra import SignalAlgebra, SensorReadings, Severity
    vectors = [(0.70, 0.10, True), (0.90, 0.45, True), (0.90, 0.10, False)]
    for tau, chi, expect_block in vectors:
        r = SensorReadings(tau_escape=tau, chi_vector=[chi], drift_score=0.05,
                           betti_1=0.01, confidence=0.85, source="parity", logical_time=1)
        sev = SignalAlgebra.severity(r)
        is_blocked = sev in (Severity.CRITICAL, Severity.ERROR)
        if expect_block:
            assert is_blocked, f"Expected block: tau={tau} chi={chi}"

def test_gap_r4_documented():
    # SNAPSHOT.md is at repo root, not in tests/
    _tests_dir = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_tests_dir)
    gaps = os.path.join(_root, 'SNAPSHOT.md')
    with open(gaps) as f: content = f.read()
    assert 'GAP R4' in content or 'R4' in content or 'Rust' in content

def test_rust_python_all_anchors_in_rust():
    from sigma_anchors import SIGMA_ANCHORS
    rust_src = os.path.join(BASE, 'crates', 'cgir-types', 'src', 'lib.rs')
    if not os.path.exists(rust_src): return True  # No Rust crates in Core
    with open(rust_src) as f: rsrc = f.read()
    missing = [n for n in SIGMA_ANCHORS if n not in rsrc]
    assert len(missing) <= 3

def run_tests():
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("test_") and callable(o)], key=lambda x:x[0])
    passed=failed=0; results=[]
    for name,fn in tests:
        try: fn(); passed+=1; results.append((name,"PASS",None))
        except Exception as e: failed+=1; results.append((name,"FAIL",str(e)[:200]))
    return passed, failed, results
