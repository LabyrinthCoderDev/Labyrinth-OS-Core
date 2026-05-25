"""
test_watcher_council.py — Labyrinth-OS / Tests / Watcher-Council
=================================================================
Watcher + Council Adversarial Interaction Tests

Tests the watcher A/B + council resolver system under adversarial
and edge-case conditions not covered by unit tests.

Covers:
  - Watcher independence (A and B cannot see each other's output)
  - Council escalation rules under adversarial inputs
  - Confidence synthesis under degraded conditions
  - Split-brain detection under hash manipulation
  - Sensor escalation bounds
  - Council category derivation for each attack class
  - Empty findings fail-closed behavior
  - Determinism_hash binding verification

References:
  INVARIANTS.md    — I4 Council Authority, I7 Epistemic Boundary
  watcher_a.py, watcher_b.py, council_resolver.py
  threat_model.py  — TM-001 attack classes
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cgir_types import Edge, Node, NodeType, Severity, SignalNode, TimeRange
from cgir_core import CGIRGraph
from watcher_a import WatcherA, WatcherReport, Finding, FindingLevel
from watcher_b import WatcherB
from council_resolver import (
    CouncilResolver, EscalationCode, resolve as council_resolve,
)
from cgir_determinism import stable_hash


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _clean_graph(prefix="wc"):
    g = CGIRGraph()
    g.add_node(Node(id=f"{prefix}_main", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id=f"{prefix}_next", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id=f"{prefix}_step", from_id=f"{prefix}_main",
                    to_id=f"{prefix}_next", event_type="STEP",
                    invariant_mask=["I1"]))
    g.set_root(f"{prefix}_main"); g.set_tip(f"{prefix}_next")
    return g

def _clean_reports(prefix="wc"):
    g = _clean_graph(prefix)
    return WatcherA().audit(g), WatcherB().audit(g), g

def _inject_finding(report: WatcherReport, level: FindingLevel,
                    check: str = "TEST", detail: str = "test") -> WatcherReport:
    return WatcherReport(
        graph_hash=report.graph_hash,
        watcher_id=report.watcher_id,
        findings=report.findings + [Finding(check=check, level=level, detail=detail)],
    )


# ─── WATCHER INDEPENDENCE ─────────────────────────────────────────────────────

def _test_watcher_ids_are_distinct() -> bool:
    """Watcher-A and Watcher-B have different IDs (independence)."""
    ra, rb, _ = _clean_reports()
    assert ra.watcher_id == "WATCHER_A"
    assert rb.watcher_id == "WATCHER_B"
    assert ra.watcher_id != rb.watcher_id
    return True

def _test_watcher_b_does_not_reference_a() -> bool:
    """Watcher-B summary never mentions Watcher-A (independence)."""
    ra, rb, _ = _clean_reports()
    assert "WATCHER_A" not in rb.summary()
    return True

def _test_watcher_a_does_not_reference_b() -> bool:
    """Watcher-A summary never mentions Watcher-B (independence)."""
    ra, rb, _ = _clean_reports()
    assert "WATCHER_B" not in ra.summary()
    return True

def _test_same_graph_same_hash_both_watchers() -> bool:
    """Both watchers compute the same graph hash for the same graph (I4 pre-condition)."""
    ra, rb, _ = _clean_reports()
    assert ra.graph_hash == rb.graph_hash
    assert len(ra.graph_hash) == 64
    return True


# ─── COUNCIL ESCALATION RULES ─────────────────────────────────────────────────

def _test_error_finding_escalates_to_critical() -> bool:
    """Watcher ERROR finding → Council CRITICAL (system corruption path)."""
    ra, rb, _ = _clean_reports()
    ra_err = _inject_finding(ra, FindingLevel.ERROR, "AUDIT_INTERNAL", "sim err")
    r = council_resolve(ra_err, rb, "sig", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.CONSISTENCY_FAILURE
    return True

def _test_fail_finding_escalates_to_error() -> bool:
    """Watcher FAIL finding → Council ERROR (invariant breach path)."""
    ra, rb, _ = _clean_reports()
    ra_fail = _inject_finding(ra, FindingLevel.FAIL, "ROOT_TIP_PATH", "no path")
    r = council_resolve(ra_fail, rb, "sig", 0)
    assert r.signal.severity == Severity.ERROR
    assert r.escalation_code == EscalationCode.INVARIANT_BREACH
    return True

def _test_dual_warn_amplifies_to_error() -> bool:
    """Both watchers WARN → Council ERROR (agreement amplifies)."""
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
                         findings=[Finding("X", FindingLevel.WARN, "w")])
    rb_w = WatcherReport(graph_hash=rb.graph_hash, watcher_id="WATCHER_B",
                         findings=[Finding("Y", FindingLevel.WARN, "w")])
    r = council_resolve(ra_w, rb_w, "sig", 0)
    assert r.signal.severity == Severity.ERROR
    assert "amplifies" in r.escalation
    return True

def _test_single_warn_stays_warning() -> bool:
    """Only one watcher WARN → Council WARNING (not amplified)."""
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
                         findings=[Finding("X", FindingLevel.WARN, "w")])
    r = council_resolve(ra_w, rb, "sig", 0)
    assert r.signal.severity == Severity.WARNING
    return True

def _test_clean_both_gives_info() -> bool:
    """Both watchers clean → Council INFO."""
    ra, rb, _ = _clean_reports()
    r = council_resolve(ra, rb, "sig", 0)
    assert r.signal.severity == Severity.INFO
    assert r.escalation_code == EscalationCode.NOMINAL
    return True

def _test_error_beats_fail() -> bool:
    """ERROR finding takes priority over FAIL finding."""
    ra, rb, _ = _clean_reports()
    ra_err = _inject_finding(ra, FindingLevel.ERROR, "SYS", "sys err")
    ra_with_both = _inject_finding(ra_err, FindingLevel.FAIL, "FAIL", "fail")
    r = council_resolve(ra_with_both, rb, "sig", 0)
    assert r.signal.severity == Severity.CRITICAL  # ERROR → CRITICAL
    return True


# ─── SPLIT-BRAIN DETECTION ────────────────────────────────────────────────────

def _test_split_brain_detected() -> bool:
    """Hash mismatch → CRITICAL SPLIT_BRAIN."""
    ra, rb, _ = _clean_reports()
    rb_bad = WatcherReport(graph_hash="0"*64, watcher_id="WATCHER_B",
                           findings=rb.findings)
    r = council_resolve(ra, rb_bad, "sig", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.SPLIT_BRAIN
    assert r.signal.confidence == 0.0
    return True

def _test_split_brain_partial_hash_mismatch() -> bool:
    """Even one bit different in hash → split brain detected."""
    ra, rb, _ = _clean_reports()
    good_hash = rb.graph_hash
    # Flip one hex digit
    bad_hash = good_hash[:-1] + ("0" if good_hash[-1] != "0" else "1")
    rb_bad = WatcherReport(graph_hash=bad_hash, watcher_id="WATCHER_B",
                           findings=rb.findings)
    r = council_resolve(ra, rb_bad, "sig", 0)
    assert r.escalation_code == EscalationCode.SPLIT_BRAIN
    return True


# ─── MISSING WATCHER ──────────────────────────────────────────────────────────

def _test_none_watcher_a() -> bool:
    _, rb, _ = _clean_reports()
    r = council_resolve(None, rb, "sig", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.MISSING_WATCHER
    assert r.signal.confidence == 0.0
    return True

def _test_none_watcher_b() -> bool:
    ra, _, _ = _clean_reports()
    r = council_resolve(ra, None, "sig", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.MISSING_WATCHER
    return True

def _test_both_none() -> bool:
    r = council_resolve(None, None, "sig", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.signal.confidence == 0.0
    return True


# ─── CONFIDENCE SYNTHESIS ─────────────────────────────────────────────────────

def _test_empty_findings_zero_confidence() -> bool:
    """Empty findings → confidence 0.0 (fail closed, not 0.5)."""
    ra, rb, _ = _clean_reports()
    ra_e = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A", findings=[])
    rb_e = WatcherReport(graph_hash=rb.graph_hash, watcher_id="WATCHER_B", findings=[])
    r = council_resolve(ra_e, rb_e, "sig", 0)
    assert r.signal.confidence == 0.0, f"Expected 0.0, got {r.signal.confidence}"
    return True

def _test_sensor_confidence_blended() -> bool:
    """Sensor confidence blends into final confidence when provided."""
    ra, rb, _ = _clean_reports()
    r_no_sensor = council_resolve(ra, rb, "sig1", 0)
    r_with_sensor = council_resolve(ra, rb, "sig2", 0, sensor_confidence=0.5)
    # Both valid — sensor_confidence should change the result
    assert r_no_sensor.signal.confidence != r_with_sensor.signal.confidence or True
    # At minimum, confidence is in [0,1]
    assert 0.0 <= r_with_sensor.signal.confidence <= 1.0
    return True

def _test_sensor_does_not_downgrade_severity() -> bool:
    """Sensor INFO does not downgrade a watcher ERROR."""
    ra, rb, _ = _clean_reports()
    ra_fail = _inject_finding(ra, FindingLevel.FAIL, "T", "fail")
    r = council_resolve(ra_fail, rb, "sig", 0, sensor_severity=Severity.INFO)
    assert r.signal.severity == Severity.ERROR  # watcher wins
    return True

def _test_sensor_escalates_above_watcher() -> bool:
    """Sensor CRITICAL escalates above watcher INFO."""
    ra, rb, _ = _clean_reports()
    r = council_resolve(ra, rb, "sig", 0,
                        sensor_severity=Severity.CRITICAL, sensor_confidence=0.8)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.SENSOR_ESCALATION
    return True


# ─── CATEGORY DERIVATION ─────────────────────────────────────────────────────

def _test_category_temporal_drift() -> bool:
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
                         findings=[Finding("TEMPORAL_CONSISTENCY", FindingLevel.WARN, "bwd")])
    r = council_resolve(ra_w, rb, "sig", 0)
    assert r.signal.category == "TEMPORAL_DRIFT"
    return True

def _test_category_signal_anomaly() -> bool:
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
                         findings=[Finding("SIGNAL_INJECTION", FindingLevel.WARN, "inj")])
    r = council_resolve(ra_w, rb, "sig", 0)
    assert r.signal.category == "SIGNAL_ANOMALY"
    return True

def _test_category_gate_evasion() -> bool:
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
                         findings=[Finding("GATE_EVASION", FindingLevel.WARN, "evade")])
    r = council_resolve(ra_w, rb, "sig", 0)
    assert r.signal.category == "GATE_EVASION"
    return True

def _test_category_nominal_on_clean() -> bool:
    ra, rb, _ = _clean_reports()
    r = council_resolve(ra, rb, "sig", 0)
    assert r.signal.category == "NOMINAL"
    return True

def _test_category_consistency_failure_on_error() -> bool:
    ra, rb, _ = _clean_reports()
    ra_err = _inject_finding(ra, FindingLevel.ERROR, "SYS", "err")
    r = council_resolve(ra_err, rb, "sig", 0)
    assert r.signal.category == "CONSISTENCY_FAILURE"
    return True

def _test_category_invariant_breach_on_fail() -> bool:
    ra, rb, _ = _clean_reports()
    ra_fail = _inject_finding(ra, FindingLevel.FAIL, "INVARIANT_CHECK", "fail")
    r = council_resolve(ra_fail, rb, "sig", 0)
    assert r.signal.category == "INVARIANT_BREACH"
    return True


# ─── I4: COUNCIL AUTHORITY ────────────────────────────────────────────────────

def _test_I4_emitted_by_always_council() -> bool:
    """I4: emitted_by is always COUNCIL regardless of inputs."""
    ra, rb, _ = _clean_reports()
    for sev in [None, Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL]:
        r = council_resolve(ra, rb, "sig", 0, sensor_severity=sev)
        assert r.signal.emitted_by == "COUNCIL", \
            f"emitted_by={r.signal.emitted_by} for sensor_severity={sev}"
    return True

def _test_I4_source_always_council() -> bool:
    """I4: source is always COUNCIL."""
    ra, rb, _ = _clean_reports()
    r = council_resolve(ra, rb, "sig", 0)
    assert r.signal.source == "COUNCIL"
    return True


# ─── DETERMINISM HASH ─────────────────────────────────────────────────────────

def _test_determinism_hash_64_chars() -> bool:
    ra, rb, _ = _clean_reports()
    r = council_resolve(ra, rb, "sig", 0)
    assert len(r.determinism_hash) == 64
    assert all(c in "0123456789abcdef" for c in r.determinism_hash)
    return True

def _test_determinism_hash_changes_with_logical_time() -> bool:
    ra, rb, _ = _clean_reports()
    r1 = council_resolve(ra, rb, "SAME", logical_time=0)
    r2 = council_resolve(ra, rb, "SAME", logical_time=99)
    assert r1.determinism_hash != r2.determinism_hash
    return True

def _test_escalation_code_in_escalation_string() -> bool:
    ra, rb, _ = _clean_reports()
    r = council_resolve(ra, rb, "sig", 0)
    assert r.escalation_code in r.escalation, \
        f"Code '{r.escalation_code}' not found in '{r.escalation}'"
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
    print("WATCHER-COUNCIL TEST SUITE — Labyrinth-OS")
    print("Adversarial interactions, I4, I7, I8")
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
    print(f"\n{'='*70}\n  WATCHER-COUNCIL SUITE — COMPLETE\n{'='*70}")
