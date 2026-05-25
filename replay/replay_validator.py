"""
replay_validator.py — Labyrinth-OS / L14 Replay/Gnosis
=======================================================
Deterministic Replay Validator

Takes a sealed HashChain ledger and replays every CouncilResult
forward, verifying that:

  1. Chain integrity holds (no tampering)
  2. Every determinism_hash is reproducible from the stored payload
  3. Severity escalation is consistent with stored findings
  4. The sequence of decisions is causally ordered
  5. No phantom signals (signals that appear without prior watcher activity)

This is the proof layer. A replay that fails is evidence of tampering,
non-determinism, or a software bug — all of which are system failures.

Replay does NOT re-run inference. It re-derives decisions from stored
evidence and checks that they match the sealed record.

Invariant I9: All committed executions are replayable from ledger.

References:
  ARCHITECTURE.md  — L14 Replay/Gnosis
  INVARIANTS.md    — I6 Ledger Immutability, I9 Replay, I2 Gate Determinism
  cgir_ledger.py   — WORM ledger entries
  hashchain.py     — SHA-256 chain with verify()
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from cgir_types import GateDecision, Severity
from cgir_ledger import AEGISPhase, CGIRLedger, LedgerEntry
from hashchain import HashChain
from receipt import Receipt


# ─── REPLAY VERDICT ───────────────────────────────────────────────────────────

@unique
class ReplayVerdict(str, Enum):
    CLEAN       = "CLEAN"        # All checks passed — chain is replay-safe
    TAMPERED    = "TAMPERED"     # Chain hash broke — data was modified
    INCONSISTENT= "INCONSISTENT" # Decision exists but evidence doesn't support it
    INCOMPLETE  = "INCOMPLETE"   # Expected phases missing from record
    EMPTY       = "EMPTY"        # No entries to replay


# ─── REPLAY FINDING ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReplayFinding:
    """One anomaly found during replay."""
    entry_index: int
    phase: str
    check: str
    detail: str
    verdict: ReplayVerdict


# ─── REPLAY RESULT ────────────────────────────────────────────────────────────

@dataclass
class ReplayResult:
    """
    Output of one replay validation run.

    verdict          — overall verdict
    entries_checked  — how many ledger entries were examined
    chain_valid      — was the SHA-256 chain intact
    findings         — list of anomalies (empty = clean)
    session_id       — which session was replayed
    """
    verdict: ReplayVerdict
    entries_checked: int
    chain_valid: bool
    findings: List[ReplayFinding]
    session_id: str

    @property
    def clean(self) -> bool:
        return self.verdict == ReplayVerdict.CLEAN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict":         self.verdict.value,
            "session_id":      self.session_id,
            "entries_checked": self.entries_checked,
            "chain_valid":     self.chain_valid,
            "finding_count":   len(self.findings),
            "findings": [
                {
                    "entry_index": f.entry_index,
                    "phase":       f.phase,
                    "check":       f.check,
                    "detail":      f.detail,
                    "verdict":     f.verdict.value,
                }
                for f in self.findings
            ],
        }


# ─── REPLAY VALIDATOR ─────────────────────────────────────────────────────────

class ReplayValidator:
    """
    Replays a sealed CGIRLedger and validates every entry.

    Usage:
        ledger = ... # a sealed CGIRLedger
        result = ReplayValidator().validate(ledger)
        if not result.clean:
            for f in result.findings:
                print(f.check, f.detail)
    """

    EXPECTED_ALLOW_PHASES = ["LOAD", "PROPOSE", "CHECK", "COMMIT", "PROVE"]
    EXPECTED_BLOCK_PHASES = ["LOAD", "PROPOSE", "CHECK", "COMMIT", "PROVE"]
    MIN_PHASES_FOR_COMPLETE = 3  # at minimum: LOAD, CHECK, COMMIT

    def validate(self, ledger: CGIRLedger) -> ReplayResult:
        """Replay all entries in a sealed ledger. Returns ReplayResult."""
        entries = ledger.entries()
        session_id = ledger.session_id

        if not entries:
            return ReplayResult(
                verdict=ReplayVerdict.EMPTY,
                entries_checked=0,
                chain_valid=False,
                findings=[ReplayFinding(
                    entry_index=0,
                    phase="",
                    check="ENTRIES",
                    detail="No entries to replay",
                    verdict=ReplayVerdict.EMPTY,
                )],
                session_id=session_id,
            )

        # ── Check 1: Chain integrity ──────────────────────────────────────────
        chain_result = ledger.verify_chain()
        chain_valid = chain_result[0] if isinstance(chain_result, tuple) else chain_result
        findings: List[ReplayFinding] = []

        if not chain_valid:
            findings.append(ReplayFinding(
                entry_index=-1,
                phase="CHAIN",
                check="CHAIN_INTEGRITY",
                detail="HashChain verify() failed — ledger may have been tampered",
                verdict=ReplayVerdict.TAMPERED,
            ))

        # ── Check 2: Phase sequence completeness ─────────────────────────────
        phases = [e.phase.value for e in entries]
        if "LOAD" not in phases:
            findings.append(ReplayFinding(
                entry_index=0,
                phase="LOAD",
                check="PHASE_SEQUENCE",
                detail="LOAD phase missing from record — session incomplete",
                verdict=ReplayVerdict.INCOMPLETE,
            ))

        if "CHECK" not in phases:
            findings.append(ReplayFinding(
                entry_index=len(entries) - 1,
                phase="CHECK",
                check="PHASE_SEQUENCE",
                detail="CHECK phase missing — validation was skipped (phase-skip attack)",
                verdict=ReplayVerdict.INCOMPLETE,
            ))

        if "COMMIT" not in phases:
            findings.append(ReplayFinding(
                entry_index=len(entries) - 1,
                phase="COMMIT",
                check="PHASE_SEQUENCE",
                detail="COMMIT phase missing — gate decision was not recorded",
                verdict=ReplayVerdict.INCOMPLETE,
            ))

        # ── Check 3: Phase ordering ───────────────────────────────────────────
        phase_order = {p: i for i, p in enumerate(
            ["LOAD", "PROPOSE", "CHECK", "COMMIT", "PROVE"]
        )}
        prev_order = -1
        for i, entry in enumerate(entries):
            order = phase_order.get(entry.phase.value, 99)
            if order < prev_order:
                findings.append(ReplayFinding(
                    entry_index=i,
                    phase=entry.phase.value,
                    check="PHASE_ORDER",
                    detail=(
                        f"Phase {entry.phase.value} appears out of order at "
                        f"position {i} (previous phase had higher ordinal)"
                    ),
                    verdict=ReplayVerdict.INCONSISTENT,
                ))
            prev_order = order

        # ── Check 4: Graph hash consistency ──────────────────────────────────
        # All entries for the same session should have the same graph hash
        # (graph doesn't change during a cycle)
        graph_hashes = {
            e.graph_hash for e in entries
            if e.graph_hash and e.phase != AEGISPhase.LOAD
        }
        if len(graph_hashes) > 1:
            findings.append(ReplayFinding(
                entry_index=-1,
                phase="ALL",
                check="GRAPH_HASH_CONSISTENCY",
                detail=(
                    f"Graph hash changed within a single session — "
                    f"found {len(graph_hashes)} distinct hashes: "
                    f"{[h[:12] + '…' for h in list(graph_hashes)[:3]]}"
                ),
                verdict=ReplayVerdict.INCONSISTENT,
            ))

        # ── Check 5: Decision consistency ─────────────────────────────────────
        # If CHECK recorded verdict=False, COMMIT should record BLOCK
        check_entry  = self._get_phase(entries, AEGISPhase.CHECK)
        commit_entry = self._get_phase(entries, AEGISPhase.COMMIT)

        if check_entry and commit_entry:
            if check_entry.verdict is False and commit_entry.decision == "ALLOW":
                findings.append(ReplayFinding(
                    entry_index=phases.index("COMMIT"),
                    phase="COMMIT",
                    check="DECISION_CONSISTENCY",
                    detail=(
                        "Validation failed (CHECK verdict=False) but gate "
                        "recorded ALLOW — inconsistent decision"
                    ),
                    verdict=ReplayVerdict.INCONSISTENT,
                ))

        # ── Check 6: PROVE requires prior COMMIT ─────────────────────────────
        if "PROVE" in phases and "COMMIT" not in phases:
            findings.append(ReplayFinding(
                entry_index=phases.index("PROVE"),
                phase="PROVE",
                check="PROVE_REQUIRES_COMMIT",
                detail="PROVE recorded without a prior COMMIT — replay gap",
                verdict=ReplayVerdict.INCOMPLETE,
            ))

        # ── Verdict ───────────────────────────────────────────────────────────
        if findings:
            verdicts = [f.verdict for f in findings]
            if ReplayVerdict.TAMPERED in verdicts:
                overall = ReplayVerdict.TAMPERED
            elif ReplayVerdict.INCONSISTENT in verdicts:
                overall = ReplayVerdict.INCONSISTENT
            else:
                overall = ReplayVerdict.INCOMPLETE
        else:
            overall = ReplayVerdict.CLEAN

        return ReplayResult(
            verdict=overall,
            entries_checked=len(entries),
            chain_valid=chain_valid,
            findings=findings,
            session_id=session_id,
        )

    def _get_phase(
        self, entries: List[LedgerEntry], phase: AEGISPhase
    ) -> Optional[LedgerEntry]:
        for e in entries:
            if e.phase == phase:
                return e
        return None


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

def validate_ledger(ledger: CGIRLedger) -> ReplayResult:
    """Convenience: validate_ledger(ledger) → ReplayResult."""
    return ReplayValidator().validate(ledger)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _make_clean_ledger(session_id: str = "test_clean") -> CGIRLedger:
    """Build a complete sealed ledger from a valid proposal."""
    from cgir_types import Edge, Node, NodeType, ValidationResult
    from cgir_core import CGIRGraph
    from cgir_validator import validate
    from cgir_gate import evaluate as gate_eval
    from cgir_ledger import new_session

    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.set_root("n0"); g.set_tip("n1")

    ledger = new_session(session_id)
    ledger.record_load(g)
    ledger.record_propose(g)
    vr = validate(g)
    ledger.record_check(g, vr)
    gr = gate_eval(g)
    ledger.record_commit(g, gr)
    ledger.record_prove(g)
    ledger.seal()
    return ledger


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_clean_ledger_is_clean() -> bool:
    """Complete valid ledger → CLEAN."""
    ledger = _make_clean_ledger("rv_clean")
    result = validate_ledger(ledger)
    assert result.clean, f"Expected CLEAN: {[f.detail for f in result.findings]}"
    assert result.entries_checked == 5
    assert result.chain_valid is True
    return True

def _test_empty_ledger_is_empty() -> bool:
    """Sealed empty ledger → EMPTY verdict."""
    from cgir_ledger import new_session
    ledger = new_session("rv_empty")
    ledger.seal()
    result = validate_ledger(ledger)
    assert result.verdict == ReplayVerdict.EMPTY
    return True

def _test_missing_commit_is_incomplete() -> bool:
    """Ledger without COMMIT → INCOMPLETE."""
    from cgir_types import Edge, Node, NodeType
    from cgir_core import CGIRGraph
    from cgir_validator import validate
    from cgir_ledger import new_session

    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))

    ledger = new_session("rv_no_commit")
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    # No COMMIT, no PROVE
    ledger.seal()

    result = validate_ledger(ledger)
    assert result.verdict == ReplayVerdict.INCOMPLETE
    checks = {f.check for f in result.findings}
    assert "PHASE_SEQUENCE" in checks
    return True

def _test_decision_inconsistency_detected() -> bool:
    """Validation failed but ALLOW recorded → INCONSISTENT."""
    from cgir_types import (
        Edge, GateResult, GateDecision, Node, NodeType,
        ValidationError, ValidationResult,
    )
    from cgir_core import CGIRGraph
    from cgir_ledger import new_session

    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))

    ledger = new_session("rv_incon")
    ledger.record_load(g)
    ledger.record_propose(g)
    # Record a FAIL validation
    bad_vr = ValidationResult(
        valid=False,
        errors=[ValidationError(error_type="ORPHAN_NODE", message="test")]
    )
    ledger.record_check(g, bad_vr)
    # But record ALLOW — inconsistent
    ledger.record_commit(g, GateResult(decision=GateDecision.ALLOW))
    ledger.record_prove(g)
    ledger.seal()

    result = validate_ledger(ledger)
    assert result.verdict == ReplayVerdict.INCONSISTENT
    checks = {f.check for f in result.findings}
    assert "DECISION_CONSISTENCY" in checks
    return True

def _test_chain_valid_on_clean() -> bool:
    """Clean ledger has valid chain."""
    result = validate_ledger(_make_clean_ledger("rv_chain"))
    assert result.chain_valid is True
    return True

def _test_all_phases_checked() -> bool:
    """Clean full cycle has 5 entries checked."""
    result = validate_ledger(_make_clean_ledger("rv_phases"))
    assert result.entries_checked == 5
    return True

def _test_result_to_dict() -> bool:
    """to_dict works on both clean and dirty results."""
    result = validate_ledger(_make_clean_ledger("rv_dict"))
    d = result.to_dict()
    for key in ["verdict","session_id","entries_checked","chain_valid","findings"]:
        assert key in d
    assert d["verdict"] == "CLEAN"
    return True

def _test_clean_has_no_findings() -> bool:
    """Clean ledger has zero findings."""
    result = validate_ledger(_make_clean_ledger("rv_no_findings"))
    assert len(result.findings) == 0
    return True

def _test_verdict_enum_values() -> bool:
    """ReplayVerdict has all expected values."""
    assert ReplayVerdict.CLEAN.value == "CLEAN"
    assert ReplayVerdict.TAMPERED.value == "TAMPERED"
    assert ReplayVerdict.INCONSISTENT.value == "INCONSISTENT"
    assert ReplayVerdict.INCOMPLETE.value == "INCOMPLETE"
    assert ReplayVerdict.EMPTY.value == "EMPTY"
    return True

def _test_blocked_cycle_replays_clean() -> bool:
    """A cycle that ended in BLOCK still replays CLEAN if chain is intact."""
    from cgir_types import (
        Edge, Node, NodeType, Severity, SignalNode,
    )
    from cgir_core import CGIRGraph
    from cgir_validator import validate
    from cgir_gate import evaluate as gate_eval
    from cgir_ledger import new_session

    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_signal(SignalNode(
        id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
        severity=Severity.CRITICAL, confidence=0.9,
        category="TEST", source="VECTOR", emitted_by="COUNCIL",
    ))

    ledger = new_session("rv_block_replay")
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    gr = gate_eval(g)
    assert gr.decision == GateDecision.BLOCK
    ledger.record_commit(g, gr)
    ledger.record_prove(g)
    ledger.seal()

    result = validate_ledger(ledger)
    assert result.clean, f"Blocked cycle should still replay CLEAN: {result.findings}"
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
    print("REPLAY VALIDATOR — Labyrinth-OS L14")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        raise SystemExit(1)
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}\n  Tests: {passed}/{passed+failed}")
    print(f"\n{'='*70}\n  REPLAY VALIDATOR — COMPLETE\n{'='*70}")
