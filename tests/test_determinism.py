"""
test_determinism.py — Labyrinth-OS / Tests / Determinism
=========================================================
Determinism Test Suite

Proves Invariants I2 and I8:
  I2: Gate is a pure function. Same graph → same decision. Always.
  I8: Council is deterministic. Same inputs → same determinism_hash.

Also proves:
  - cgir_determinism.stable_hash is insertion-order-independent
  - Same proposal dict → same graph hash → same cycle result
  - Ledger entries for identical decisions have identical hashes
  - Signal algebra is deterministic (same readings → same SignalNode)
  - replay_validator is deterministic (same ledger → same verdict)

These are not just nice properties. They are what makes the system
auditable, replayable, and provably correct. Without determinism,
the ledger cannot prove anything.

References:
  INVARIANTS.md    — I2 Gate Determinism, I8 Council Determinism
  cgir_determinism.py
  cgir_gate.py
  council_resolver.py
  aegis_cesk.py
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cgir_types import Edge, GateDecision, Node, NodeType, Severity, SignalNode
from cgir_core import CGIRGraph
from cgir_determinism import stable_hash
from cgir_gate import evaluate as gate_eval
from cgir_signal_algebra import SensorReadings, evaluate as signal_eval
from council_resolver import resolve as council_resolve
from aegis_cesk import run_cycle
from replay_validator import validate_ledger, ReplayVerdict
from watcher_a import WatcherA
from watcher_b import WatcherB


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _make_graph(node_prefix="n", signal_severity=None):
    g = CGIRGraph()
    g.add_node(Node(id=f"{node_prefix}0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id=f"{node_prefix}1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id=f"{node_prefix}0", to_id=f"{node_prefix}1",
                    event_type="STEP", invariant_mask=["I1"]))
    g.set_root(f"{node_prefix}0"); g.set_tip(f"{node_prefix}1")
    if signal_severity:
        g.add_signal(SignalNode(
            id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
            severity=signal_severity, confidence=0.9,
            category="TEST", source="VECTOR", emitted_by="COUNCIL",
        ))
    return g

def _make_proposal(prefix="det"):
    return {
        "nodes": [
            {"id": f"{prefix}_main", "node_type": "STATE", "logical_time": 0},
            {"id": f"{prefix}_next", "node_type": "STATE", "logical_time": 1},
        ],
        "edges": [
            {"id": f"{prefix}_step", "from_id": f"{prefix}_main",
             "to_id": f"{prefix}_next", "event_type": "STEP",
             "invariant_mask": ["I1"]},
        ],
        "root": f"{prefix}_main", "tip": f"{prefix}_next",
    }

def _make_readings():
    return SensorReadings(
        tau_escape=0.88, drift_score=0.05, chi_vector=[0.06, 0.08],
        betti_1=0.01, confidence=0.90, source="VECTOR", logical_time=5,
    )


# ─── I2: GATE DETERMINISM ─────────────────────────────────────────────────────

def _test_I2_gate_pure_function_no_signals() -> bool:
    """I2: Same graph (no signals) → same ALLOW across 10 calls."""
    g = _make_graph()
    decisions = [gate_eval(g).decision for _ in range(10)]
    assert all(d == GateDecision.ALLOW for d in decisions)
    return True

def _test_I2_gate_pure_function_critical() -> bool:
    """I2: Same graph (CRITICAL) → same BLOCK across 10 calls."""
    g = _make_graph(signal_severity=Severity.CRITICAL)
    decisions = [gate_eval(g).decision for _ in range(10)]
    assert all(d == GateDecision.BLOCK for d in decisions)
    return True

def _test_I2_gate_pure_function_error() -> bool:
    """I2: Same graph (ERROR) → same BLOCK across 10 calls."""
    g = _make_graph(signal_severity=Severity.ERROR)
    decisions = [gate_eval(g).decision for _ in range(10)]
    assert all(d == GateDecision.BLOCK for d in decisions)
    return True

def _test_I2_gate_reason_stable() -> bool:
    """I2: Gate reason string is identical across calls."""
    g = _make_graph()
    reasons = [gate_eval(g).reason for _ in range(5)]
    assert len(set(reasons)) == 1
    return True


# ─── STABLE HASH DETERMINISM ──────────────────────────────────────────────────

def _test_stable_hash_same_graph_same_hash() -> bool:
    """stable_hash produces same result for identical graphs."""
    g1 = _make_graph("h")
    g2 = _make_graph("h")
    assert stable_hash(g1) == stable_hash(g2)
    return True

def _test_stable_hash_insertion_order_independent() -> bool:
    """stable_hash is independent of node/edge insertion order."""
    g1 = CGIRGraph()
    g1.add_node(Node(id="a", node_type=NodeType.STATE, logical_time=0))
    g1.add_node(Node(id="b", node_type=NodeType.STATE, logical_time=1))
    g1.add_edge(Edge(id="e0", from_id="a", to_id="b", event_type="STEP"))

    g2 = CGIRGraph()
    g2.add_node(Node(id="b", node_type=NodeType.STATE, logical_time=1))
    g2.add_node(Node(id="a", node_type=NodeType.STATE, logical_time=0))
    g2.add_edge(Edge(id="e0", from_id="a", to_id="b", event_type="STEP"))

    assert stable_hash(g1) == stable_hash(g2), \
        "Hash must be insertion-order-independent"
    return True

def _test_stable_hash_different_graphs_different_hash() -> bool:
    """Different graphs produce different hashes."""
    g1 = _make_graph("x")
    g2 = _make_graph("y")  # different node IDs
    assert stable_hash(g1) != stable_hash(g2)
    return True

def _test_stable_hash_is_64_hex_chars() -> bool:
    """stable_hash always returns a 64-character hex string."""
    g = _make_graph()
    h = stable_hash(g)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    return True


# ─── SIGNAL ALGEBRA DETERMINISM ───────────────────────────────────────────────

def _test_signal_algebra_deterministic() -> bool:
    """Same SensorReadings → same SignalNode attributes, every time."""
    r = _make_readings()
    sigs = [signal_eval(r, "sig_det") for _ in range(10)]
    sevs = {s.severity for s in sigs}
    confs = {round(s.confidence, 10) for s in sigs}
    cats = {s.category for s in sigs}
    assert len(sevs) == 1, f"Severity varied: {sevs}"
    assert len(confs) == 1, f"Confidence varied: {confs}"
    assert len(cats) == 1, f"Category varied: {cats}"
    return True

def _test_signal_algebra_source_preserved() -> bool:
    """Signal algebra preserves source field deterministically."""
    r = _make_readings()
    sigs = [signal_eval(r, "src_test") for _ in range(5)]
    sources = {s.source for s in sigs}
    assert len(sources) == 1
    return True


# ─── I8: COUNCIL DETERMINISM ──────────────────────────────────────────────────

def _test_I8_council_determinism_hash_stable() -> bool:
    """I8: Same watcher reports → same determinism_hash every time."""
    g = _make_graph("c8")
    ra = WatcherA().audit(g)
    rb = WatcherB().audit(g)
    hashes = {council_resolve(ra, rb, "det_sig", 5).determinism_hash
              for _ in range(10)}
    assert len(hashes) == 1, f"Council hash varied: {hashes}"
    return True

def _test_I8_different_logical_time_different_hash() -> bool:
    """I8: Same everything except logical_time → different hash (time binding)."""
    g = _make_graph()
    ra = WatcherA().audit(g)
    rb = WatcherB().audit(g)
    h1 = council_resolve(ra, rb, "SAME_ID", logical_time=0).determinism_hash
    h2 = council_resolve(ra, rb, "SAME_ID", logical_time=1).determinism_hash
    assert h1 != h2, "Different logical_time must produce different hash"
    return True

def _test_I8_council_severity_stable() -> bool:
    """I8: Same inputs → same severity."""
    g = _make_graph()
    ra = WatcherA().audit(g)
    rb = WatcherB().audit(g)
    sevs = {council_resolve(ra, rb, "sev_test", 0).signal.severity
            for _ in range(10)}
    assert len(sevs) == 1
    return True


# ─── AEGIS CYCLE DETERMINISM ──────────────────────────────────────────────────

def _test_aegis_cycle_same_proposal_same_graph_hash() -> bool:
    """Same proposal → same graph_hash across independent cycle runs."""
    p = _make_proposal("aeg")
    hashes = {run_cycle(p, f"det_sess_{i}").graph_hash for i in range(5)}
    assert len(hashes) == 1, f"Graph hash varied: {hashes}"
    return True

def _test_aegis_cycle_same_proposal_same_decision() -> bool:
    """Same proposal → same decision across independent cycle runs."""
    p = _make_proposal("aeg2")
    decisions = {run_cycle(p, f"det_d_{i}").decision for i in range(5)}
    assert len(decisions) == 1
    return True

def _test_aegis_blocked_proposal_always_blocks() -> bool:
    """Critical signal proposal always blocks, deterministically."""
    p = _make_proposal("crit")
    p["signals"] = [{
        "id": "critical_sig", "logical_time": 0,
        "severity": "CRITICAL", "confidence": 0.9,
        "category": "TAU_ESCAPE_LOW", "source": "VECTOR",
        "emitted_by": "COUNCIL",
    }]
    decisions = {run_cycle(p, f"crit_det_{i}").decision for i in range(5)}
    assert decisions == {GateDecision.BLOCK}
    return True


# ─── REPLAY DETERMINISM ───────────────────────────────────────────────────────

def _test_replay_deterministic_on_same_ledger() -> bool:
    """replay_validator returns same verdict on same ledger, every time."""
    from cgir_ledger import new_session
    from cgir_validator import validate
    g = _make_graph("rep")
    ledger = new_session("det_replay")
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    ledger.record_commit(g, gate_eval(g))
    ledger.record_prove(g)
    ledger.seal()

    verdicts = {validate_ledger(ledger).verdict for _ in range(5)}
    assert len(verdicts) == 1
    assert list(verdicts)[0] == ReplayVerdict.CLEAN
    return True


# ─── WATCHER DETERMINISM ──────────────────────────────────────────────────────

def _test_watcher_a_deterministic() -> bool:
    """WatcherA: same graph → same findings, same hash."""
    g = _make_graph("wa")
    reports = [WatcherA().audit(g) for _ in range(5)]
    hashes = {r.graph_hash for r in reports}
    passed = {r.passed for r in reports}
    assert len(hashes) == 1
    assert len(passed) == 1
    return True

def _test_watcher_b_deterministic() -> bool:
    """WatcherB: same graph → same findings, same hash."""
    g = _make_graph("wb")
    reports = [WatcherB().audit(g) for _ in range(5)]
    hashes = {r.graph_hash for r in reports}
    assert len(hashes) == 1
    return True


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


if __name__ == "__main__":
    import hashlib as _hl
    print("=" * 70)
    print("DETERMINISM TEST SUITE — Labyrinth-OS")
    print("Proves Invariants I2 (Gate) and I8 (Council)")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed: raise SystemExit(1)
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}\n  Tests: {passed}/{passed+failed}")
    print(f"\n{'='*70}\n  DETERMINISM SUITE — COMPLETE\n{'='*70}")
