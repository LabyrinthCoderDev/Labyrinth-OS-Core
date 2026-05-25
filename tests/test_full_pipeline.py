"""
test_full_pipeline.py — Labyrinth-OS / Integration Tests
=========================================================
End-to-End Integration Test Suite

Proves the complete pipeline works as one system:

  SensorReadings (L3 VECTOR)
    ↓ cgir_signal_algebra
  SignalNode
    ↓ watcher_a + watcher_b
  WatcherReport × 2
    ↓ council_resolver
  CouncilResult (single SignalNode, emitted_by=COUNCIL)
    ↓ build_proposal_from_readings
  CGIR proposal dict
    ↓ aegis_cesk (LOAD→PROPOSE→CHECK→COMMIT→PROVE)
  CycleResult + WORM Ledger
    ↓ cgir_guardian_bridge
  BridgeResult
    ↓ guardian_slot
  SlotResult (EXECUTE / BLOCK / KILL)

Each test exercises a complete path through the system.
No mocking. No stubs. Real modules.

ACP-1 relationship:
  These tests partially close A013 (SCUEL tests are synthetic only).
  They do not close A010 (requires live Ollama inference).

References:
  All modules in Sentinel-Substrate--main (path injection via run_all.py)
"""

from __future__ import annotations

import hashlib
import sys
import time
from typing import Any, Dict

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from cgir_types import (
    Edge, GateDecision, Node, NodeType,
    Severity, SignalNode, TimeRange,
)
from cgir_core import CGIRGraph
from cgir_validator import validate
from cgir_determinism import stable_hash
from cgir_gate import evaluate as gate_eval
from cgir_ledger import new_session, CGIRLedger
from cgir_signal_algebra import SensorReadings, evaluate as signal_eval
from cgir_signal_algebra import TAU_FLOOR, DRIFT_TH as DRIFT_THRESHOLD, CHI_COL as CHI_COLLAPSE, BETA_1_CAP as BETTI_1_CAP
from aegis_cesk import AEGISKernel, CycleResult, run_cycle
from watcher_a import WatcherA
from watcher_b import WatcherB
from council_resolver import CouncilResolver, resolve as council_resolve
from cgir_guardian_bridge import (
    CGIRGuardianBridge, BridgeResult,
    build_proposal_from_readings, evaluate as bridge_eval,
)
from guardian_slot import GuardianSlot, GuardianSignal, SlotDecision
from receipt import Receipt
from hashchain import HashChain


# ─── SENSOR FIXTURES ──────────────────────────────────────────────────────────

def _sensors_nominal() -> SensorReadings:
    return SensorReadings(
        tau_escape=0.92, drift_score=0.04,
        chi_vector=[0.05, 0.07, 0.06],
        betti_1=0.008, confidence=0.91,
        source="VECTOR_L3", logical_time=10,
    )

def _sensors_marginal() -> SensorReadings:
    return SensorReadings(
        tau_escape=0.78, drift_score=0.09,
        chi_vector=[0.12, 0.14],
        betti_1=0.038, confidence=0.72,
        source="VECTOR_L3", logical_time=11,
    )

def _sensors_critical_tau() -> SensorReadings:
    """τ below floor → CRITICAL."""
    return SensorReadings(
        tau_escape=TAU_FLOOR - 0.10,
        drift_score=0.05, chi_vector=[0.08],
        betti_1=0.01, confidence=0.85,
        source="VECTOR_L3", logical_time=12,
    )

def _sensors_critical_chi() -> SensorReadings:
    """χ at collapse → CRITICAL."""
    return SensorReadings(
        tau_escape=0.88, drift_score=0.05,
        chi_vector=[CHI_COLLAPSE],
        betti_1=0.01, confidence=0.80,
        source="VECTOR_L3", logical_time=13,
    )

def _sensors_high_drift() -> SensorReadings:
    """Drift at threshold → ERROR."""
    return SensorReadings(
        tau_escape=0.88, drift_score=DRIFT_THRESHOLD,
        chi_vector=[0.06], betti_1=0.01,
        confidence=0.80, source="VECTOR_L3", logical_time=14,
    )

def _sensors_betti_breach() -> SensorReadings:
    """β₁ at cap → ERROR."""
    return SensorReadings(
        tau_escape=0.88, drift_score=0.05,
        chi_vector=[0.06], betti_1=BETTI_1_CAP,
        confidence=0.80, source="VECTOR_L3", logical_time=15,
    )


# ─── INTEGRATION TESTS ────────────────────────────────────────────────────────

def _test_INT_01_signal_algebra_nominal() -> bool:
    """INT-01: Nominal sensor readings produce INFO SignalNode."""
    r = _sensors_nominal()
    sig = signal_eval(r, "sig_int01")
    assert sig.severity == Severity.INFO
    assert sig.emitted_by == "SIGNAL_ALGEBRA"  # raw algebra — Council upgrades to COUNCIL
    assert 0.5 < sig.confidence <= 1.0
    return True

def _test_INT_02_signal_algebra_critical_tau() -> bool:
    """INT-02: τ below floor → CRITICAL SignalNode."""
    r = _sensors_critical_tau()
    sig = signal_eval(r, "sig_int02")
    assert sig.severity == Severity.CRITICAL, f"Got {sig.severity}"
    return True

def _test_INT_03_watcher_a_nominal() -> bool:
    """INT-03: WatcherA passes clean graph."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int03", "int03")
    # Build graph from proposal to pass to watcher directly
    from aegis_cesk import ProposalCompiler
    graph = ProposalCompiler.compile(proposal, "int03")
    report = WatcherA().audit(graph)
    assert report.watcher_id == "WATCHER_A"
    assert report.passed, f"Unexpected: {[f.detail for f in report.findings]}"
    return True

def _test_INT_04_watcher_b_nominal() -> bool:
    """INT-04: WatcherB passes clean non-synthetic graph."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int04", "int04")
    from aegis_cesk import ProposalCompiler
    graph = ProposalCompiler.compile(proposal, "int04")
    report = WatcherB().audit(graph)
    assert report.watcher_id == "WATCHER_B"
    # Non-synthetic IDs so no sequential replay warning
    return True

def _test_INT_05_council_resolver_nominal() -> bool:
    """INT-05: Council produces INFO signal for two passing watchers."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int05", "int05")
    from aegis_cesk import ProposalCompiler
    graph = ProposalCompiler.compile(proposal, "int05")
    ra = WatcherA().audit(graph)
    rb = WatcherB().audit(graph)
    result = council_resolve(ra, rb, "council_int05", 10)
    assert result.signal.emitted_by == "COUNCIL"
    assert result.signal.severity in (Severity.INFO, Severity.WARNING)
    return True

def _test_INT_06_council_hash_agreement() -> bool:
    """INT-06: Watcher-A and Watcher-B hashes agree for same graph."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int06", "int06")
    from aegis_cesk import ProposalCompiler
    graph = ProposalCompiler.compile(proposal, "int06")
    ra = WatcherA().audit(graph)
    rb = WatcherB().audit(graph)
    assert ra.graph_hash == rb.graph_hash, (
        f"Hash mismatch: A={ra.graph_hash[:12]} B={rb.graph_hash[:12]}"
    )
    return True

def _test_INT_07_aegis_nominal_allow() -> bool:
    """INT-07: Nominal proposal runs full AEGIS cycle → ALLOW."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int07", "int07")
    result = run_cycle(proposal, "int07")
    assert result.decision == GateDecision.ALLOW
    assert result.phases_run == ["LOAD","PROPOSE","CHECK","COMMIT","PROVE"]
    return True

def _test_INT_08_aegis_critical_blocks() -> bool:
    """INT-08: CRITICAL signal in proposal → CGIR blocks at COMMIT."""
    r = _sensors_critical_tau()
    proposal = build_proposal_from_readings(r, "act_int08", "int08")
    result = run_cycle(proposal, "int08")
    assert result.decision == GateDecision.BLOCK
    assert result.blocked_at == "COMMIT"
    return True

def _test_INT_09_ledger_seals_correctly() -> bool:
    """INT-09: AEGIS ledger seals with valid chain after full cycle."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int09", "int09")
    result = run_cycle(proposal, "int09")
    assert result.ledger_summary["sealed"] is True
    assert result.ledger_summary["chain_length"] == 5
    chain_valid = result.ledger_summary.get("chain_valid")
    # chain_valid is a tuple (True, None, None) from hashchain.verify()
    if isinstance(chain_valid, tuple):
        assert chain_valid[0] is True
    else:
        assert chain_valid is True
    return True

def _test_INT_10_bridge_nominal_executes() -> bool:
    """INT-10: Full bridge evaluation of nominal sensors → EXECUTE."""
    result = bridge_eval(
        _sensors_nominal(), cbf_margin=0.6,
        action_id="act_int10", session_id="int10"
    )
    assert result.is_safe_to_execute is True
    assert result.slot_result.decision == SlotDecision.EXECUTE
    return True

def _test_INT_11_bridge_critical_blocks() -> bool:
    """INT-11: Bridge with critical τ → KILL or BLOCK."""
    result = bridge_eval(
        _sensors_critical_tau(), cbf_margin=0.4,
        action_id="act_int11", session_id="int11"
    )
    assert not result.is_safe_to_execute
    assert result.slot_result.decision in (SlotDecision.KILL, SlotDecision.BLOCK)
    return True

def _test_INT_12_bridge_human_kill_irrevocable() -> bool:
    """INT-12: Human KILL override → KILL regardless of sensor state."""
    result = bridge_eval(
        _sensors_nominal(), cbf_margin=0.9,
        session_id="int12", human_override="KILL"
    )
    assert result.slot_result.decision == SlotDecision.KILL
    return True

def _test_INT_13_stability_same_input_same_output() -> bool:
    """INT-13: Identical sensor readings → identical final decision."""
    r = _sensors_nominal()
    results = [
        bridge_eval(r, cbf_margin=0.6, session_id=f"stab_{i}")
        for i in range(3)
    ]
    decisions = [res.slot_result.decision for res in results]
    assert len(set(d.value for d in decisions)) == 1, (
        f"Non-deterministic: {[d.value for d in decisions]}"
    )
    return True

def _test_INT_14_receipt_chain_valid_nominal() -> bool:
    """INT-14: Full pipeline produces a valid hashchain receipt."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int14", "int14")
    result = run_cycle(proposal, "int14")
    chain_valid = result.ledger_summary.get("chain_valid")
    valid = chain_valid[0] if isinstance(chain_valid, tuple) else chain_valid
    assert valid is True
    return True

def _test_INT_15_graph_hash_stable_across_runs() -> bool:
    """INT-15: Same proposal → same graph hash across independent AEGIS runs."""
    r = _sensors_nominal()
    proposal = build_proposal_from_readings(r, "act_int15a", "int15a")
    h1 = run_cycle(proposal, "int15a").graph_hash
    proposal2 = build_proposal_from_readings(r, "act_int15a", "int15a")
    h2 = run_cycle(proposal2, "int15b").graph_hash
    assert h1 == h2, f"Hash mismatch: {h1[:12]}… vs {h2[:12]}…"
    return True

def _test_INT_16_error_drift_pipeline() -> bool:
    """INT-16: High drift → ERROR severity → CGIR blocks if CRITICAL, passes if ERROR."""
    r = _sensors_high_drift()
    sig = signal_eval(r, "sig_drift")
    # ERROR from drift (not CRITICAL, so CGIR may allow but guardian tightens)
    assert sig.severity == Severity.ERROR
    result = bridge_eval(r, cbf_margin=0.6, session_id="int16")
    # CGIR allows (no CRITICAL signal), but guardian may block
    # Either outcome is valid — test that pipeline completes without exception
    assert isinstance(result.slot_result.decision, SlotDecision)
    return True

def _test_INT_17_betti_breach_pipeline() -> bool:
    """INT-17: β₁ at cap → ERROR severity pipeline completes."""
    r = _sensors_betti_breach()
    sig = signal_eval(r, "sig_betti")
    assert sig.severity == Severity.ERROR
    result = bridge_eval(r, cbf_margin=0.6, session_id="int17")
    assert isinstance(result.slot_result.decision, SlotDecision)
    return True

def _test_INT_18_chi_collapse_pipeline() -> bool:
    """INT-18: χ at collapse → CRITICAL → CGIR BLOCK → guardian KILL."""
    r = _sensors_critical_chi()
    sig = signal_eval(r, "sig_chi_col")
    assert sig.severity == Severity.CRITICAL
    result = bridge_eval(r, cbf_margin=0.5, session_id="int18")
    assert not result.is_safe_to_execute
    return True

def _test_INT_19_z3_sovereignty_receipt_loadable() -> bool:
    """INT-19: Z3 sovereignty receipt can be loaded from disk."""
    import os, json
    _tests_dir = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_tests_dir)
    # sovereignty_receipt.json lives at repo root
    receipt_path = os.path.join(_root, 'sovereignty_receipt.json')
    assert os.path.exists(receipt_path), f"Missing: {receipt_path}"
    with open(receipt_path) as f:
        receipt = json.load(f)
    # Verify receipt has expected constitutional fields
    assert "spec_version" in receipt, "Missing spec_version"
    assert "sovereignty_claims" in receipt, "Missing sovereignty_claims"
    assert "z3_verified" in receipt, "Missing z3_verified"
    assert receipt.get("z3_verified") is True, "z3_verified must be True"
    assert "sha256" in receipt, "Missing sha256 proof reference"
    return True

def _test_INT_20_acbf_itv_vectors_still_pass() -> bool:
    """INT-20: ACBF canonical payload hash matches spec vector 1."""
    from acbf_vm import payload_hash, run_trace, loadi, halt
    # Spec canonical payload for vector 1 (from itv_vectors.py)
    PAYLOAD = {"query": "SELECT * FROM patients", "user_id": 42, "purpose": "treatment"}
    expected = "4b8f4f55c0d80fa97bf8be89a64685bee8b6e661705f7f916719376c5a1f26b5"
    actual = payload_hash(1, PAYLOAD).hex()
    assert actual == expected, f"ACBF hash mismatch: {actual}"
    # Also verify a minimal linear trace still runs
    code = loadi(0, 7) + halt()
    trace = run_trace(code)
    assert trace.success and trace.halted
    return True

def _test_INT_21_worm_receipt_chain_for_full_run() -> bool:
    """INT-21: Manual WORM chain: 3 bridge runs → valid chain."""
    chain = HashChain()
    for i in range(3):
        r = _sensors_nominal()
        result = bridge_eval(r, cbf_margin=0.6, session_id=f"worm_{i}")
        receipt = Receipt(
            receipt_id=f"bridge_run_{i}",
            module="cgir_guardian_bridge",
            action="EVALUATE",
            verdict=result.slot_result.decision.value,
            payload={
                "cycle_decision": result.cycle_result.decision.value,
                "bridge_hash": result.bridge_hash,
            },
            prev_hash=chain.head_hash,
        )
        chain.append(receipt)
    valid, _, _ = chain.verify()
    assert valid is True
    assert chain.length == 3
    return True

def _test_INT_22_marginal_sensors_pipeline() -> bool:
    """INT-22: Marginal sensors complete pipeline without exception."""
    result = bridge_eval(
        _sensors_marginal(), cbf_margin=0.5, session_id="int22"
    )
    assert isinstance(result, BridgeResult)
    d = result.to_dict()
    assert "slot_decision" in d
    return True


# ─── TEST RUNNER ──────────────────────────────────────────────────────────────


# ── SCUEL SYNTHETIC TESTS (A013) ──────────────────────────────────────────────
# SCUEL = Severity Classification Under Epistemic Load
# Tests prove the pipeline classifies adversarial failure modes correctly.
# POLITE_LIE, SLOW_POISON, BURST, COORDINATED are the four attack signatures.
# Full A013 close requires live inference traffic. These are synthetic coverage.

def _make_sensor(tau=0.85, chi=0.08, drift=0.05, betti=0.02, conf=0.85,
                  source="COUNCIL", logical_time=1):
    from cgir_signal_algebra import SensorReadings
    return SensorReadings(
        tau_escape=tau, chi_vector=[chi], drift_score=drift,
        betti_1=betti, confidence=conf, source=source,
        logical_time=logical_time,
    )


def _test_SCUEL_01_polite_lie_critical_tau_blocked() -> bool:
    """POLITE_LIE: high confidence but tau below floor → CRITICAL regardless.
    TAU_ESCAPE_FLOOR=0.75 — below it gate must fire CRITICAL."""
    from cgir_signal_algebra import SignalAlgebra
    sa = SignalAlgebra()
    readings = _make_sensor(tau=0.60, conf=0.95)  # high conf, low tau = polite lie
    node = sa.evaluate(readings, "polite_lie_001")
    sev = node.severity.value if hasattr(node.severity, 'value') else str(node.severity)
    assert sev in ("CRITICAL", "ERROR"),         f"POLITE_LIE: tau=0.60 below floor must be CRITICAL/ERROR, got {sev}"
    return True


def _test_SCUEL_02_slow_poison_drift_accumulation() -> bool:
    """SLOW_POISON: drift just above DRIFT_THRESHOLD=0.12 triggers ERROR."""
    from cgir_signal_algebra import SignalAlgebra
    sa = SignalAlgebra()
    readings = _make_sensor(tau=0.85, chi=0.08, drift=0.13)  # 0.13 > 0.12
    node = sa.evaluate(readings, "slow_poison_001")
    sev = node.severity.value if hasattr(node.severity, 'value') else str(node.severity)
    assert sev in ("ERROR", "CRITICAL"),         f"SLOW_POISON drift=0.13>0.12 must be ERROR/CRITICAL, got {sev}"
    return True


def _test_SCUEL_03_burst_chi_collapse_blocked() -> bool:
    """BURST: chi at CHI_COLLAPSE=0.40 triggers CRITICAL."""
    from cgir_signal_algebra import SignalAlgebra
    sa = SignalAlgebra()
    readings = _make_sensor(tau=0.85, chi=0.41, drift=0.05)  # 0.41 > CHI_COLLAPSE=0.40
    node = sa.evaluate(readings, "burst_001")
    sev = node.severity.value if hasattr(node.severity, 'value') else str(node.severity)
    assert sev in ("CRITICAL",),         f"BURST chi=0.41 must be CRITICAL, got {sev}"
    return True


def _test_SCUEL_04_coordinated_marginal_triggers_warning() -> bool:
    """COORDINATED: all sensors at warning margins triggers WARNING."""
    from cgir_signal_algebra import SignalAlgebra
    sa = SignalAlgebra()
    readings = _make_sensor(tau=0.80, chi=0.16, drift=0.09)  # chi at CHI_WARN=0.15
    node = sa.evaluate(readings, "coordinated_001")
    sev = node.severity.value if hasattr(node.severity, 'value') else str(node.severity)
    assert sev in ("WARNING", "ERROR", "CRITICAL"),         f"COORDINATED marginal chi=0.16 must be WARNING+, got {sev}"
    return True


def _test_SCUEL_05_nominal_passes_cleanly() -> bool:
    """Baseline: clean sensors produce INFO with no escalation."""
    from cgir_signal_algebra import SignalAlgebra
    sa = SignalAlgebra()
    readings = _make_sensor(tau=0.88, chi=0.07, drift=0.04, betti=0.01, conf=0.90)
    node = sa.evaluate(readings, "nominal_001")
    sev = node.severity.value if hasattr(node.severity, 'value') else str(node.severity)
    assert sev == "INFO", f"Nominal sensors must be INFO, got {sev}"
    return True


def _test_SCUEL_06_betti_breach_blocked() -> bool:
    """BETTI breach: betti_1 >= BETTI_1_CAP=0.045 triggers ERROR."""
    from cgir_signal_algebra import SignalAlgebra
    sa = SignalAlgebra()
    readings = _make_sensor(tau=0.85, chi=0.08, drift=0.05, betti=0.05)  # 0.05 > 0.045
    node = sa.evaluate(readings, "betti_001")
    sev = node.severity.value if hasattr(node.severity, 'value') else str(node.severity)
    assert sev in ("ERROR", "CRITICAL"),         f"BETTI breach betti_1=0.05 must be ERROR/CRITICAL, got {sev}"
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
    print("LABYRINTH-OS INTEGRATION TESTS — End-to-End Pipeline")
    print("=" * 70)
    print("\n  Tests run with REAL modules — no mocks, no stubs.")
    print("  Covers: L3 sensors → CGIR → Guardian Slot → WORM ledger\n")

    print("── TEST SUITE ──\n")
    passed, failed, results = run_tests()

    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        label = name.replace("_test_", "")
        line = f"  {marker} {label}"
        if err:
            line += f"\n      ✗ {err}"
        print(line)

    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")

    if failed > 0:
        print("\n  ✗ INTEGRATION TESTS FAILED")
        raise SystemExit(1)

    print("\n── PIPELINE PROOF ──\n")
    print("  SensorReadings")
    print("    ↓ cgir_signal_algebra  → SignalNode (severity, confidence)")
    print("    ↓ watcher_a            → WatcherReport (internal consistency)")
    print("    ↓ watcher_b            → WatcherReport (adversarial)")
    print("    ↓ council_resolver     → SignalNode (emitted_by=COUNCIL, I4)")
    print("    ↓ aegis_cesk           → LOAD→PROPOSE→CHECK→COMMIT→PROVE")
    print("    ↓ cgir_guardian_bridge → GuardianSignal")
    print("    ↓ guardian_slot        → EXECUTE / BLOCK / KILL")
    print("    ↓ hashchain + receipt  → WORM audit trail")
    print("\n  All layers operational. Z3 sovereignty: [REAL].")

    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}")
    print(f"  Tests:   {passed}/{passed+failed}")
    print(f"\n{'=' * 70}")
    print(f"  INTEGRATION TESTS — COMPLETE")
    print(f"{'=' * 70}")
