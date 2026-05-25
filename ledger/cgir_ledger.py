"""
cgir_ledger.py — Labyrinth-OS / CGIR Phase 2
=============================================
Causal Graph Intermediate Representation — State Transition Ledger

Wires receipt.py + hashchain.py into the CGIR execution path.

Every AEGIS state transition (LOAD → PROPOSE → CHECK → COMMIT → PROVE)
produces an immutable Receipt appended to the HashChain.

The ledger is the proof layer. If it is not in the ledger, it did not happen.
If the ledger chain is broken, the system stops.

Responsibilities:
  - One ledger per execution session.
  - Each phase transition → one Receipt → one HashChain entry.
  - Gate decisions recorded verbatim (ALLOW / BLOCK / reason).
  - Graph hashes recorded alongside decisions.
  - Read-back: full session replay by chain.

Rules:
  - Append-only. No modification. No deletion.
  - Fail closed: any write failure → raise, do not swallow.
  - No implicit behavior: every field in every receipt is explicit.
  - The chain hash covers the receipt payload, not just metadata.

References:
  ARCHITECTURE.md  — L13 Ledger/Chronicle
  receipt.py       — Immutable atomic receipt (25/25)
  hashchain.py     — SHA-256 append-only chain (29/29)
  INVARIANTS.md    — I6 Ledger Immutability, I9 Replay
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from cgir_types import GateDecision, GateResult, ValidationResult
from cgir_determinism import stable_hash
from cgir_core import CGIRGraph
from receipt import Receipt
from hashchain import HashChain


# ─── PHASE CONSTANTS ──────────────────────────────────────────────────────────

@unique
class AEGISPhase(str, Enum):
    """
    The five phases of an AEGIS execution cycle.
    Recorded in order: every transition produces one ledger entry.
    """
    LOAD    = "LOAD"      # Proposal received and typed into CGIRGraph
    PROPOSE = "PROPOSE"   # Graph presented to validator
    CHECK   = "CHECK"     # Validation result recorded
    COMMIT  = "COMMIT"    # Gate decision recorded
    PROVE   = "PROVE"     # Final hash + receipt chain entry


# ─── LEDGER ENTRY ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LedgerEntry:
    """
    One entry in the session ledger.

    phase         — which AEGIS phase produced this entry
    graph_hash    — stable_hash of the CGIRGraph at this point (or "" if N/A)
    decision      — gate decision if phase == COMMIT, else None
    verdict       — validation valid/invalid if phase == CHECK, else None
    error_count   — number of validation errors if phase == CHECK
    note          — free-form string for non-graph events
    wall_clock    — Unix timestamp (float, seconds)
    session_id    — identifies the session this entry belongs to
    """
    phase: AEGISPhase
    graph_hash: str
    session_id: str
    wall_clock: float
    decision: Optional[str] = None       # "ALLOW" | "BLOCK" | None
    decision_reason: Optional[str] = None
    verdict: Optional[bool] = None       # True=valid, False=invalid, None=N/A
    error_count: int = 0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "phase":      self.phase.value,
            "graph_hash": self.graph_hash,
            "session_id": self.session_id,
            "wall_clock": self.wall_clock,
            "note":       self.note,
        }
        if self.decision is not None:
            d["decision"] = self.decision
        if self.decision_reason is not None:
            d["decision_reason"] = self.decision_reason
        if self.verdict is not None:
            d["verdict"] = self.verdict
            d["error_count"] = self.error_count
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


# ─── CGIR LEDGER ──────────────────────────────────────────────────────────────

class CGIRLedger:
    """
    Session ledger for one AEGIS execution cycle.

    Usage:
        ledger = CGIRLedger(session_id="sess_001")
        ledger.record_load(graph)
        ledger.record_propose(graph)
        ledger.record_check(graph, validation_result)
        ledger.record_commit(graph, gate_result)
        ledger.record_prove(graph)
        summary = ledger.seal()

    After seal() the chain is closed. Further writes raise LedgerSealedError.
    """

    class LedgerSealedError(RuntimeError):
        """Raised when attempting to write to a sealed ledger."""

    class LedgerWriteError(RuntimeError):
        """Raised when a ledger write fails. System must stop."""

    def __init__(self, session_id: str) -> None:
        if not session_id or not isinstance(session_id, str):
            raise ValueError("session_id must be a non-empty string")
        self._session_id = session_id
        self._chain = HashChain()
        self._entries: List[LedgerEntry] = []
        self._sealed = False
        self._seal_hash: Optional[str] = None

    # ── Write ──────────────────────────────────────────────────────────

    def record_load(self, graph: CGIRGraph, note: str = "") -> LedgerEntry:
        """Record LOAD phase: proposal received and typed."""
        return self._append(AEGISPhase.LOAD, graph, note=note)

    def record_propose(self, graph: CGIRGraph, note: str = "") -> LedgerEntry:
        """Record PROPOSE phase: graph presented to validator."""
        return self._append(AEGISPhase.PROPOSE, graph, note=note)

    def record_check(self, graph: CGIRGraph,
                     validation: ValidationResult,
                     note: str = "") -> LedgerEntry:
        """Record CHECK phase: validation result."""
        return self._append(
            AEGISPhase.CHECK, graph,
            verdict=validation.valid,
            error_count=len(validation.errors),
            note=note,
        )

    def record_commit(self, graph: CGIRGraph,
                      gate_result: GateResult,
                      note: str = "") -> LedgerEntry:
        """Record COMMIT phase: gate decision."""
        return self._append(
            AEGISPhase.COMMIT, graph,
            decision=gate_result.decision.value,
            decision_reason=gate_result.reason,
            note=note,
        )

    def record_prove(self, graph: CGIRGraph, note: str = "") -> LedgerEntry:
        """Record PROVE phase: final hash anchored to chain."""
        return self._append(AEGISPhase.PROVE, graph, note=note)

    def log_predicate_block(
        self,
        proposal_id: str,
        violations: List[str],
        verdict_hash: str,
        source: str = "LOGICAL_SENTINEL",
    ) -> LedgerEntry:
        """
        G12: Log a PREDICATE_BLOCK — proposal rejected by the LogicalSentinel
        predicate layer before reaching the Sigma Anchor gate.

        This is distinct from a GATE BLOCK (Sigma threshold violation).
        Predicate blocks are logged with their specific invariant violations
        (Φ1, Φ2, Φ3) so they are replayable and distinguishable from sensor blocks.

        Records in the COMMIT phase with decision="PREDICATE_BLOCK".
        """
        note = f"PREDICATE_BLOCK: {'; '.join(violations)}"
        return self._append(
            AEGISPhase.COMMIT,
            graph=None,
            decision="PREDICATE_BLOCK",
            decision_reason=note,
            note=(
                f"proposal_id={proposal_id} "
                f"verdict_hash={verdict_hash[:16]}... "
                f"source={source} "
                f"violations={len(violations)}"
            ),
        )

    def _append(self, phase: AEGISPhase, graph: Optional[CGIRGraph],
                decision: Optional[str] = None,
                decision_reason: Optional[str] = None,
                verdict: Optional[bool] = None,
                error_count: int = 0,
                note: str = "") -> LedgerEntry:
        """
        Internal: build entry, write receipt, append to chain.
        Fails closed on any error.
        """
        if self._sealed:
            raise self.LedgerSealedError(
                f"Ledger for session '{self._session_id}' is sealed. "
                f"Cannot record phase {phase.value}."
            )

        graph_hash = stable_hash(graph) if graph is not None else ""

        entry = LedgerEntry(
            phase=phase,
            graph_hash=graph_hash,
            session_id=self._session_id,
            wall_clock=time.time(),
            decision=decision,
            decision_reason=decision_reason,
            verdict=verdict,
            error_count=error_count,
            note=note,
        )

        try:
            _verdict = ("ALLOW" if decision == "ALLOW" else
                        "BLOCK" if decision == "BLOCK" else
                        "VALID" if verdict is True else
                        "INVALID" if verdict is False else
                        "RECORD")
            receipt = Receipt(
                receipt_id=f"{self._session_id}.{phase.value}.{len(self._entries)}",
                module=f"cgir_ledger.{phase.value}",
                action=phase.value,
                verdict=_verdict,
                payload={"entry": entry.to_dict()},
                prev_hash=self._chain.head_hash,
            )
            self._chain.append(receipt)
        except Exception as exc:
            raise self.LedgerWriteError(
                f"Ledger write failed at phase {phase.value}: {exc}"
            ) from exc

        self._entries.append(entry)
        return entry

    # ── Seal ───────────────────────────────────────────────────────────

    def seal(self) -> Dict[str, Any]:
        """
        Close the ledger. Returns a summary dict.
        After sealing, no further writes are possible.
        """
        if self._sealed:
            return self._summary()

        self._sealed = True
        self._seal_hash = self._chain.head_hash
        return self._summary()

    def _summary(self) -> Dict[str, Any]:
        return {
            "session_id":  self._session_id,
            "entry_count": len(self._entries),
            "sealed":      self._sealed,
            "seal_hash":   self._seal_hash,
            "phases":      [e.phase.value for e in self._entries],
            "chain_length":self._chain.length,
            "chain_valid": self._chain.verify()[0],
        }

    # ── Read ───────────────────────────────────────────────────────────

    @property
    def is_sealed(self) -> bool:
        return self._sealed

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def session_id(self) -> str:
        return self._session_id

    def entries(self) -> List[LedgerEntry]:
        """Return a copy of the entry list."""
        return list(self._entries)

    def verify_chain(self):
        """Verify the underlying hash chain integrity."""
        return self._chain.verify()

    def get_entry(self, phase: AEGISPhase) -> Optional[LedgerEntry]:
        """Return the first entry with the given phase, or None."""
        for e in self._entries:
            if e.phase == phase:
                return e
        return None

    def last_decision(self) -> Optional[GateDecision]:
        """Return the gate decision from the COMMIT entry, or None."""
        e = self.get_entry(AEGISPhase.COMMIT)
        if e and e.decision:
            return GateDecision(e.decision)
        return None


# ─── MODULE-LEVEL CONVENIENCE ─────────────────────────────────────────────────

def new_session(session_id: str) -> CGIRLedger:
    """Create a new ledger for a session."""
    return CGIRLedger(session_id=session_id)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _make_valid_graph():
    from cgir_types import Edge, Node, NodeType
    from cgir_core import CGIRGraph
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.set_root("n0"); g.set_tip("n1")
    return g


def _make_graph_with_critical():
    from cgir_types import Edge, Node, NodeType, Severity, SignalNode
    g = _make_valid_graph()
    sig = SignalNode(
        id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
        severity=Severity.CRITICAL, confidence=0.95,
        category="TEST", source="VECTOR", emitted_by="COUNCIL",
    )
    g.add_signal(sig)
    return g


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_ledger_creation() -> bool:
    """CGIRLedger can be created with a valid session_id."""
    ledger = CGIRLedger("sess_001")
    assert ledger.session_id == "sess_001"
    assert ledger.entry_count == 0
    assert not ledger.is_sealed
    return True


def _test_ledger_rejects_empty_session_id() -> bool:
    """Empty session_id raises ValueError."""
    try:
        CGIRLedger("")
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass
    return True


def _test_record_load() -> bool:
    """record_load produces one entry with phase LOAD."""
    ledger = CGIRLedger("sess_load")
    g = _make_valid_graph()
    entry = ledger.record_load(g)
    assert entry.phase == AEGISPhase.LOAD
    assert len(entry.graph_hash) == 64
    assert ledger.entry_count == 1
    return True


def _test_record_propose() -> bool:
    """record_propose produces PROPOSE entry."""
    ledger = CGIRLedger("sess_propose")
    g = _make_valid_graph()
    entry = ledger.record_propose(g)
    assert entry.phase == AEGISPhase.PROPOSE
    return True


def _test_record_check_valid() -> bool:
    """record_check with valid result records verdict=True."""
    from cgir_validator import validate
    ledger = CGIRLedger("sess_check_valid")
    g = _make_valid_graph()
    vr = validate(g)
    assert vr.valid
    entry = ledger.record_check(g, vr)
    assert entry.phase == AEGISPhase.CHECK
    assert entry.verdict is True
    assert entry.error_count == 0
    return True


def _test_record_check_invalid() -> bool:
    """record_check with invalid result records verdict=False."""
    from cgir_types import ValidationError, ValidationResult
    ledger = CGIRLedger("sess_check_invalid")
    g = _make_valid_graph()
    vr = ValidationResult(valid=False, errors=[
        ValidationError(error_type="ORPHAN_NODE", message="test")
    ])
    entry = ledger.record_check(g, vr)
    assert entry.verdict is False
    assert entry.error_count == 1
    return True


def _test_record_commit_allow() -> bool:
    """record_commit with ALLOW gate result records decision=ALLOW."""
    ledger = CGIRLedger("sess_commit_allow")
    g = _make_valid_graph()
    gr = GateResult(decision=GateDecision.ALLOW)
    entry = ledger.record_commit(g, gr)
    assert entry.phase == AEGISPhase.COMMIT
    assert entry.decision == "ALLOW"
    return True


def _test_record_commit_block() -> bool:
    """record_commit with BLOCK gate result records decision=BLOCK."""
    ledger = CGIRLedger("sess_commit_block")
    g = _make_valid_graph()
    gr = GateResult(decision=GateDecision.BLOCK, reason="CRITICAL signal")
    entry = ledger.record_commit(g, gr)
    assert entry.decision == "BLOCK"
    assert "CRITICAL" in (entry.decision_reason or "")
    return True


def _test_record_prove() -> bool:
    """record_prove produces PROVE entry."""
    ledger = CGIRLedger("sess_prove")
    g = _make_valid_graph()
    entry = ledger.record_prove(g)
    assert entry.phase == AEGISPhase.PROVE
    assert len(entry.graph_hash) == 64
    return True


def _test_full_cycle_all_phases() -> bool:
    """Full LOAD→PROPOSE→CHECK→COMMIT→PROVE cycle records 5 entries."""
    from cgir_validator import validate
    from cgir_gate import evaluate
    ledger = CGIRLedger("sess_full")
    g = _make_valid_graph()
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    ledger.record_commit(g, evaluate(g))
    ledger.record_prove(g)
    assert ledger.entry_count == 5
    phases = [e.phase.value for e in ledger.entries()]
    assert phases == ["LOAD","PROPOSE","CHECK","COMMIT","PROVE"]
    return True


def _test_seal_produces_summary() -> bool:
    """seal() returns a valid summary dict."""
    from cgir_validator import validate
    ledger = CGIRLedger("sess_seal")
    g = _make_valid_graph()
    ledger.record_load(g)
    summary = ledger.seal()
    assert summary["session_id"] == "sess_seal"
    assert summary["sealed"] is True
    assert summary["entry_count"] == 1
    assert isinstance(summary["seal_hash"], str)
    return True


def _test_sealed_ledger_rejects_writes() -> bool:
    """Writing to a sealed ledger raises LedgerSealedError."""
    ledger = CGIRLedger("sess_sealed_write")
    g = _make_valid_graph()
    ledger.seal()
    try:
        ledger.record_load(g)
        raise AssertionError("Should have raised LedgerSealedError")
    except CGIRLedger.LedgerSealedError:
        pass
    return True


def _test_chain_is_valid_after_full_cycle() -> bool:
    """HashChain is valid after a full cycle."""
    from cgir_validator import validate
    from cgir_gate import evaluate
    ledger = CGIRLedger("sess_chain_valid")
    g = _make_valid_graph()
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    ledger.record_commit(g, evaluate(g))
    ledger.record_prove(g)
    assert ledger.verify_chain()[0] is True
    return True


def _test_same_graph_same_hash_across_entries() -> bool:
    """Same graph produces same hash in every entry."""
    ledger = CGIRLedger("sess_hash_stable")
    g = _make_valid_graph()
    e1 = ledger.record_load(g)
    e2 = ledger.record_propose(g)
    assert e1.graph_hash == e2.graph_hash
    return True


def _test_entry_to_dict_has_required_keys() -> bool:
    """LedgerEntry.to_dict has all required keys."""
    ledger = CGIRLedger("sess_dict")
    g = _make_valid_graph()
    entry = ledger.record_load(g)
    d = entry.to_dict()
    for key in ["phase", "graph_hash", "session_id", "wall_clock"]:
        assert key in d, f"Missing key: {key}"
    return True


def _test_last_decision_allow() -> bool:
    """last_decision returns ALLOW after ALLOW commit."""
    ledger = CGIRLedger("sess_last_allow")
    g = _make_valid_graph()
    ledger.record_commit(g, GateResult(decision=GateDecision.ALLOW))
    assert ledger.last_decision() == GateDecision.ALLOW
    return True


def _test_last_decision_block() -> bool:
    """last_decision returns BLOCK after BLOCK commit."""
    ledger = CGIRLedger("sess_last_block")
    g = _make_valid_graph()
    ledger.record_commit(g, GateResult(decision=GateDecision.BLOCK, reason="CRITICAL"))
    assert ledger.last_decision() == GateDecision.BLOCK
    return True


def _test_last_decision_none_when_no_commit() -> bool:
    """last_decision returns None when no COMMIT recorded."""
    ledger = CGIRLedger("sess_no_commit")
    g = _make_valid_graph()
    ledger.record_load(g)
    assert ledger.last_decision() is None
    return True


def _test_get_entry_returns_correct_phase() -> bool:
    """get_entry returns the right phase entry."""
    ledger = CGIRLedger("sess_get_entry")
    g = _make_valid_graph()
    ledger.record_load(g)
    ledger.record_propose(g)
    entry = ledger.get_entry(AEGISPhase.PROPOSE)
    assert entry is not None
    assert entry.phase == AEGISPhase.PROPOSE
    return True


def _test_get_entry_none_for_missing_phase() -> bool:
    """get_entry returns None for a phase not yet recorded."""
    ledger = CGIRLedger("sess_get_missing")
    g = _make_valid_graph()
    ledger.record_load(g)
    assert ledger.get_entry(AEGISPhase.PROVE) is None
    return True


def _test_entries_returns_copy() -> bool:
    """entries() returns a copy — modifying it does not affect ledger."""
    ledger = CGIRLedger("sess_copy")
    g = _make_valid_graph()
    ledger.record_load(g)
    lst = ledger.entries()
    lst.clear()
    assert ledger.entry_count == 1
    return True


def _test_seal_summary_chain_valid() -> bool:
    """seal summary includes chain_valid=True for clean session."""
    from cgir_validator import validate
    ledger = CGIRLedger("sess_seal_chain")
    g = _make_valid_graph()
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    summary = ledger.seal()
    assert summary["chain_valid"] is True
    return True


def _test_new_session_factory() -> bool:
    """new_session() creates a CGIRLedger."""
    ledger = new_session("factory_sess")
    assert isinstance(ledger, CGIRLedger)
    assert ledger.session_id == "factory_sess"
    return True


def _test_critical_signal_records_block() -> bool:
    """Full cycle with CRITICAL signal records BLOCK decision."""
    from cgir_validator import validate
    from cgir_gate import evaluate
    ledger = CGIRLedger("sess_critical")
    g = _make_graph_with_critical()
    ledger.record_load(g)
    ledger.record_propose(g)
    ledger.record_check(g, validate(g))
    gate = evaluate(g)
    ledger.record_commit(g, gate)
    assert ledger.last_decision() == GateDecision.BLOCK
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
    print("CGIR LEDGER — Labyrinth-OS Phase 2")
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

    # Demo: full cycle
    print("\n── DEMO: Full AEGIS cycle ──\n")
    from cgir_types import Edge, Node, NodeType, Severity, SignalNode
    from cgir_validator import validate
    from cgir_gate import evaluate

    g = _make_valid_graph()
    ledger = new_session("demo_session_001")

    e1 = ledger.record_load(g,    note="Proposal received from planner")
    e2 = ledger.record_propose(g, note="Graph typed: 2 nodes, 1 edge")
    e3 = ledger.record_check(g, validate(g), note="Validator ran")
    e4 = ledger.record_commit(g, evaluate(g), note="Gate evaluated")
    e5 = ledger.record_prove(g,  note="Proof anchored")
    summary = ledger.seal()

    for e in ledger.entries():
        d = e.decision or e.verdict
        print(f"  {e.phase.value:8}  hash={e.graph_hash[:12]}…  {d or ''}")

    print(f"\n  chain_length: {summary['chain_length']}")
    print(f"  chain_valid:  {summary['chain_valid']}")
    print(f"  seal_hash:    {(summary['seal_hash'] or '')[:16]}…")

    with open(__file__, "rb") as f:
        file_hash = _hl.sha256(f.read()).hexdigest()

    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {file_hash}")
    print(f"  File:    cgir_ledger.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 2 Step 1: cgir_ledger.py — COMPLETE")
    print(f"{'=' * 70}")
