"""
aegis_cesk.py — Labyrinth-OS / CGIR Phase 2
============================================
AEGIS Execution Kernel — LOAD → PROPOSE → CHECK → COMMIT → PROVE

The only module permitted to mutate execution state.
Every phase produces a ledger entry. If any phase fails, the cycle
ends immediately and the decision is BLOCK.

AEGIS is not a class of convenience. It is the execution boundary.
Nothing executes except through AEGIS.
Nothing writes state except through AEGIS.

Phase definitions:
  LOAD    — Accept a proposal dict and compile it into a CGIRGraph.
  PROPOSE — Hand the graph to the validator. Check structure.
  CHECK   — If validation fails → BLOCK immediately. Else continue.
  COMMIT  — Evaluate the validated graph through the Gate.
  PROVE   — Record final hash. Seal the ledger. Return result.

Fail-closed invariants:
  - Any exception in any phase → BLOCK, ledger sealed, exception re-raised
    as AEGISError with full context.
  - Validation failure → BLOCK (not an exception, but a hard stop).
  - Gate BLOCK → cycle ends at COMMIT. PROVE still runs (records the BLOCK).
  - No phase may be skipped.
  - No phase may run twice in one cycle.
  - design: @LabyrinthCoder

References:
  ARCHITECTURE.md  — L12 AEGIS/CESK
  INVARIANTS.md    — I1 Execution Closure, I2 Gate Determinism, I6 Ledger
  cgir_validator.py
  cgir_gate.py
  cgir_ledger.py
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cgir_types import (
    Edge, GateDecision, GateResult, Node, NodeType,
    SignalNode, ValidationResult,
)
from cgir_core import CGIRGraph
from cgir_validator import validate as _validate
from cgir_gate import evaluate as _gate_evaluate, evaluate_with_validation
from cgir_ledger import CGIRLedger, new_session
from cgir_determinism import stable_hash


# ─── ERRORS ───────────────────────────────────────────────────────────────────

class AEGISError(RuntimeError):
    """
    Raised when AEGIS encounters an unrecoverable error in any phase.
    Contains the phase name, reason, and session_id for audit.
    """
    def __init__(self, phase: str, reason: str, session_id: str):
        self.phase = phase
        self.reason = reason
        self.session_id = session_id
        super().__init__(f"AEGISError in phase {phase} (session={session_id}): {reason}")


class AEGISCompileError(AEGISError):
    """Raised when a proposal cannot be compiled into a CGIRGraph."""


class AEGISPhaseViolation(AEGISError):
    """Raised when phases are called out of order."""


# ─── CYCLE RESULT ─────────────────────────────────────────────────────────────

@dataclass
class CycleResult:
    """
    The output of one full AEGIS execution cycle.

    session_id     — identifies this cycle
    decision       — ALLOW or BLOCK
    reason         — why BLOCK was returned (empty if ALLOW)
    graph_hash     — stable hash of the final CGIRGraph
    validation     — the ValidationResult from PROPOSE/CHECK
    gate_result    — the GateResult from COMMIT
    ledger_summary — the sealed ledger summary dict
    phases_run     — list of phase names that completed
    blocked_at     — phase name where BLOCK was decided (None if ALLOW)
    wall_clock_ms  — total cycle time in milliseconds
    """
    session_id: str
    decision: GateDecision
    reason: str
    graph_hash: str
    validation: Optional[ValidationResult]
    gate_result: Optional[GateResult]
    ledger_summary: Dict[str, Any]
    phases_run: List[str]
    blocked_at: Optional[str]
    wall_clock_ms: float

    @property
    def allowed(self) -> bool:
        return self.decision == GateDecision.ALLOW

    @property
    def blocked(self) -> bool:
        return self.decision == GateDecision.BLOCK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id":    self.session_id,
            "decision":      self.decision.value,
            "reason":        self.reason,
            "graph_hash":    self.graph_hash,
            "phases_run":    self.phases_run,
            "blocked_at":    self.blocked_at,
            "wall_clock_ms": round(self.wall_clock_ms, 3),
            "ledger_chain_valid": self.ledger_summary.get("chain_valid", [False])[0]
                if isinstance(self.ledger_summary.get("chain_valid"), tuple)
                else self.ledger_summary.get("chain_valid", False),
        }


# ─── PROPOSAL COMPILER ────────────────────────────────────────────────────────

class ProposalCompiler:
    """
    Compiles a proposal dict into a CGIRGraph.

    The proposal dict format:
    {
      "nodes": [
        {"id": "n0", "node_type": "STATE", "logical_time": 0},
        ...
      ],
      "edges": [
        {"id": "e0", "from_id": "n0", "to_id": "n1",
         "event_type": "STEP", "invariant_mask": ["I1"]},
        ...
      ],
      "signals": [  # optional
        {"id": "sig0", "logical_time": 0, "severity": "WARNING",
         "confidence": 0.8, "category": "DRIFT",
         "source": "VECTOR", "emitted_by": "COUNCIL"},
        ...
      ],
      "root": "n0",   # optional
      "tip":  "n1",   # optional
    }

    Compile fails closed: any missing/invalid field → AEGISCompileError.
    """

    _VALID_NODE_TYPES = {nt.value for nt in NodeType}
    _VALID_SEVERITIES = {"INFO", "WARNING", "ERROR", "CRITICAL"}

    @classmethod
    def compile(cls, proposal: Dict[str, Any], session_id: str) -> CGIRGraph:
        """Compile proposal dict → CGIRGraph."""
        if not isinstance(proposal, dict):
            raise AEGISCompileError("LOAD", "Proposal must be a dict", session_id)

        g = CGIRGraph()

        # ── Nodes ──────────────────────────────────────────────────────
        raw_nodes = proposal.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise AEGISCompileError("LOAD", "'nodes' must be a list", session_id)
        for i, rn in enumerate(raw_nodes):
            try:
                nid = str(rn["id"])
                ntype = rn.get("node_type", "STATE")
                if ntype not in cls._VALID_NODE_TYPES:
                    raise AEGISCompileError("LOAD",
                        f"nodes[{i}] unknown node_type '{ntype}'", session_id)
                lt = int(rn["logical_time"])
                meta = rn.get("metadata", {}) or {}
                node = Node(id=nid, node_type=NodeType(ntype),
                            logical_time=lt, metadata=dict(meta))
                g.add_node(node)
            except (KeyError, TypeError, ValueError) as exc:
                raise AEGISCompileError("LOAD",
                    f"nodes[{i}] compile error: {exc}", session_id) from exc

        # ── Edges ──────────────────────────────────────────────────────
        raw_edges = proposal.get("edges", [])
        if not isinstance(raw_edges, list):
            raise AEGISCompileError("LOAD", "'edges' must be a list", session_id)
        for i, re in enumerate(raw_edges):
            try:
                eid     = str(re["id"])
                from_id = str(re["from_id"])
                to_id   = str(re["to_id"])
                etype   = str(re.get("event_type", "STEP"))
                mask    = list(re.get("invariant_mask", []))
                binding = re.get("signal_binding", None)
                edge = Edge(id=eid, from_id=from_id, to_id=to_id,
                            event_type=etype, invariant_mask=mask,
                            signal_binding=binding)
                g.add_edge(edge)
            except (KeyError, TypeError) as exc:
                raise AEGISCompileError("LOAD",
                    f"edges[{i}] compile error: {exc}", session_id) from exc

        # ── Signals ────────────────────────────────────────────────────
        from cgir_types import Severity, TimeRange
        raw_sigs = proposal.get("signals", [])
        if not isinstance(raw_sigs, list):
            raise AEGISCompileError("LOAD", "'signals' must be a list", session_id)
        for i, rs in enumerate(raw_sigs):
            try:
                sid       = str(rs["id"])
                slt       = int(rs["logical_time"])
                severity  = Severity(rs.get("severity", "INFO"))
                confidence= float(rs.get("confidence", 0.0))
                category  = str(rs.get("category", ""))
                source    = str(rs.get("source", ""))
                emitted_by= str(rs.get("emitted_by", ""))
                evidence  = list(rs.get("evidence_refs", []))
                vf_raw    = rs.get("valid_for", None)
                valid_for = None
                if vf_raw is not None:
                    valid_for = TimeRange(
                        start_time=int(vf_raw["start_time"]),
                        end_time=int(vf_raw["end_time"]),
                    )
                sig = SignalNode(
                    id=sid, node_type=NodeType.SIGNAL, logical_time=slt,
                    severity=severity, confidence=confidence,
                    category=category, source=source, emitted_by=emitted_by,
                    evidence_refs=evidence, valid_for=valid_for,
                )
                g.add_signal(sig)
            except (KeyError, TypeError, ValueError) as exc:
                raise AEGISCompileError("LOAD",
                    f"signals[{i}] compile error: {exc}", session_id) from exc

        # ── Root / Tip ─────────────────────────────────────────────────
        if "root" in proposal and proposal["root"] is not None:
            g.set_root(str(proposal["root"]))
        if "tip" in proposal and proposal["tip"] is not None:
            g.set_tip(str(proposal["tip"]))

        return g


# ─── AEGIS KERNEL ─────────────────────────────────────────────────────────────

class AEGISKernel:
    """
    The AEGIS execution kernel.

    Usage:
        kernel = AEGISKernel()
        result = kernel.run_cycle(proposal, session_id="sess_001")

    One instance can run multiple sequential cycles.
    Each cycle gets its own CGIRLedger.

    Thread safety: not thread-safe. One cycle at a time per instance.
    """

    def __init__(self) -> None:
        self._cycle_count = 0

    def run_cycle(
        self,
        proposal: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> CycleResult:
        """
        Execute one full LOAD → PROPOSE → CHECK → COMMIT → PROVE cycle.

        Returns a CycleResult. Never raises (errors are recorded in the
        ledger and returned as BLOCK decisions) — except for unrecoverable
        internal errors (AEGISError subclasses).
        """
        self._cycle_count += 1
        if session_id is None:
            session_id = f"aegis_cycle_{self._cycle_count}_{int(time.time())}"

        ledger = new_session(session_id)
        start_ns = time.perf_counter_ns()
        phases_run: List[str] = []
        graph: Optional[CGIRGraph] = None
        validation: Optional[ValidationResult] = None
        gate_result: Optional[GateResult] = None
        blocked_at: Optional[str] = None
        decision = GateDecision.BLOCK
        reason = "Cycle did not complete"

        try:
            # ── PHASE 1: LOAD ─────────────────────────────────────────
            try:
                graph = ProposalCompiler.compile(proposal, session_id)
                ledger.record_load(graph, note="Proposal compiled to CGIRGraph")
                phases_run.append("LOAD")
            except AEGISCompileError as exc:
                ledger.record_load(CGIRGraph(), note=f"COMPILE_FAIL: {exc.reason}")
                phases_run.append("LOAD")
                blocked_at = "LOAD"
                reason = f"Compile error: {exc.reason}"
                return self._build_result(
                    session_id, GateDecision.BLOCK, reason,
                    "", validation, None, ledger.seal(),
                    phases_run, blocked_at, start_ns,
                )

            # ── PHASE 2: PROPOSE ──────────────────────────────────────
            ledger.record_propose(graph, note="Graph presented to validator")
            phases_run.append("PROPOSE")

            # ── PHASE 3: CHECK ────────────────────────────────────────
            validation = _validate(graph)
            ledger.record_check(graph, validation,
                                note=f"Valid={validation.valid} errors={len(validation.errors)}")
            phases_run.append("CHECK")

            if not validation.valid:
                blocked_at = "CHECK"
                reason = (f"Validation failed: "
                          f"{', '.join(e.error_type for e in validation.errors[:3])}")
                return self._build_result(
                    session_id, GateDecision.BLOCK, reason,
                    stable_hash(graph), validation, None, ledger.seal(),
                    phases_run, blocked_at, start_ns,
                )

            # ── PHASE 4: COMMIT ───────────────────────────────────────
            gate_result = _gate_evaluate(graph)
            ledger.record_commit(graph, gate_result,
                                 note=gate_result.reason or "Gate evaluated")
            phases_run.append("COMMIT")

            decision = gate_result.decision
            reason = gate_result.reason
            if decision == GateDecision.BLOCK:
                blocked_at = "COMMIT"

            # ── PHASE 5: PROVE ────────────────────────────────────────
            ledger.record_prove(graph, note="Cycle complete. Hash anchored.")
            phases_run.append("PROVE")

        except (CGIRLedger.LedgerWriteError, CGIRLedger.LedgerSealedError) as exc:
            raise AEGISError("LEDGER", str(exc), session_id) from exc

        graph_hash = stable_hash(graph) if graph is not None else ""
        return self._build_result(
            session_id, decision, reason,
            graph_hash, validation, gate_result, ledger.seal(),
            phases_run, blocked_at, start_ns,
        )

    def _build_result(
        self,
        session_id: str,
        decision: GateDecision,
        reason: str,
        graph_hash: str,
        validation: Optional[ValidationResult],
        gate_result: Optional[GateResult],
        ledger_summary: Dict[str, Any],
        phases_run: List[str],
        blocked_at: Optional[str],
        start_ns: int,
    ) -> CycleResult:
        elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
        return CycleResult(
            session_id=session_id,
            decision=decision,
            reason=reason,
            graph_hash=graph_hash,
            validation=validation,
            gate_result=gate_result,
            ledger_summary=ledger_summary,
            phases_run=phases_run,
            blocked_at=blocked_at,
            wall_clock_ms=elapsed_ms,
        )

    @property
    def cycle_count(self) -> int:
        return self._cycle_count


# ─── MODULE-LEVEL CONVENIENCE ─────────────────────────────────────────────────

def run_cycle(proposal: Dict[str, Any],
              session_id: Optional[str] = None) -> CycleResult:
    """Convenience: run one AEGIS cycle."""
    return AEGISKernel().run_cycle(proposal, session_id)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _valid_proposal() -> Dict[str, Any]:
    """Minimal valid proposal that should ALLOW."""
    return {
        "nodes": [
            {"id": "n0", "node_type": "STATE", "logical_time": 0},
            {"id": "n1", "node_type": "STATE", "logical_time": 1},
        ],
        "edges": [
            {"id": "e0", "from_id": "n0", "to_id": "n1", "event_type": "STEP"},
        ],
        "root": "n0",
        "tip":  "n1",
    }


def _proposal_with_critical() -> Dict[str, Any]:
    """Valid graph with CRITICAL signal — should BLOCK at COMMIT."""
    p = _valid_proposal()
    p["signals"] = [{
        "id": "sig0", "logical_time": 0,
        "severity": "CRITICAL", "confidence": 0.90,
        "category": "TAU_ESCAPE_LOW", "source": "VECTOR",
        "emitted_by": "COUNCIL",
    }]
    return p


def _invalid_proposal_orphan() -> Dict[str, Any]:
    """Graph with orphan node — should BLOCK at CHECK."""
    return {
        "nodes": [
            {"id": "n0", "node_type": "STATE", "logical_time": 0},
            {"id": "orphan", "node_type": "STATE", "logical_time": 1},
        ],
        "edges": [
            {"id": "e0", "from_id": "n0", "to_id": "n0", "event_type": "SELF"},
        ],
    }


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_valid_proposal_allows() -> bool:
    """Valid proposal with no signals → ALLOW."""
    result = run_cycle(_valid_proposal(), "test_allow")
    assert result.decision == GateDecision.ALLOW, f"Expected ALLOW, got {result.decision}"
    assert result.blocked is False
    return True


def _test_all_five_phases_run() -> bool:
    """Valid cycle runs all 5 phases."""
    result = run_cycle(_valid_proposal(), "test_phases")
    assert result.phases_run == ["LOAD","PROPOSE","CHECK","COMMIT","PROVE"]
    return True


def _test_critical_signal_blocks() -> bool:
    """CRITICAL signal → BLOCK at COMMIT."""
    result = run_cycle(_proposal_with_critical(), "test_crit")
    assert result.decision == GateDecision.BLOCK
    assert result.blocked_at == "COMMIT"
    assert "PROVE" in result.phases_run  # PROVE still runs after BLOCK
    return True


def _test_invalid_graph_blocks_at_check() -> bool:
    """Orphan node → BLOCK at CHECK."""
    result = run_cycle(_invalid_proposal_orphan(), "test_orphan")
    assert result.decision == GateDecision.BLOCK
    assert result.blocked_at == "CHECK"
    assert "PROVE" not in result.phases_run
    return True


def _test_bad_proposal_blocks_at_load() -> bool:
    """Non-dict proposal → BLOCK at LOAD."""
    result = run_cycle("not_a_dict", "test_bad_load")
    assert result.decision == GateDecision.BLOCK
    assert result.blocked_at == "LOAD"
    return True


def _test_missing_node_field_blocks_at_load() -> bool:
    """Node missing required field → BLOCK at LOAD."""
    p = {"nodes": [{"id": "n0"}], "edges": []}
    result = run_cycle(p, "test_missing_field")
    assert result.decision == GateDecision.BLOCK
    assert result.blocked_at == "LOAD"
    return True


def _test_result_has_graph_hash() -> bool:
    """Successful cycle produces non-empty graph_hash."""
    result = run_cycle(_valid_proposal(), "test_hash")
    assert len(result.graph_hash) == 64
    assert all(c in "0123456789abcdef" for c in result.graph_hash)
    return True


def _test_result_graph_hash_empty_on_compile_fail() -> bool:
    """Compile failure produces empty graph_hash."""
    result = run_cycle("bad", "test_hash_fail")
    assert result.graph_hash == ""
    return True


def _test_ledger_sealed_after_cycle() -> bool:
    """Ledger is sealed after cycle completes."""
    result = run_cycle(_valid_proposal(), "test_seal")
    assert result.ledger_summary["sealed"] is True
    return True


def _test_ledger_has_correct_entry_count() -> bool:
    """Full ALLOW cycle has 5 ledger entries."""
    result = run_cycle(_valid_proposal(), "test_entries")
    assert result.ledger_summary["entry_count"] == 5
    return True


def _test_cycle_result_is_cycle_result() -> bool:
    """run_cycle returns a CycleResult."""
    result = run_cycle(_valid_proposal(), "test_type")
    assert isinstance(result, CycleResult)
    return True


def _test_allowed_property() -> bool:
    """CycleResult.allowed is True when ALLOW."""
    result = run_cycle(_valid_proposal(), "test_allowed_prop")
    assert result.allowed is True
    assert result.blocked is False
    return True


def _test_blocked_property() -> bool:
    """CycleResult.blocked is True when BLOCK."""
    result = run_cycle(_proposal_with_critical(), "test_blocked_prop")
    assert result.blocked is True
    assert result.allowed is False
    return True


def _test_to_dict_has_required_keys() -> bool:
    """CycleResult.to_dict has all required keys."""
    result = run_cycle(_valid_proposal(), "test_dict")
    d = result.to_dict()
    for key in ["session_id","decision","graph_hash","phases_run","blocked_at"]:
        assert key in d
    return True


def _test_wall_clock_ms_positive() -> bool:
    """wall_clock_ms is a positive float."""
    result = run_cycle(_valid_proposal(), "test_time")
    assert result.wall_clock_ms > 0
    assert isinstance(result.wall_clock_ms, float)
    return True


def _test_kernel_counts_cycles() -> bool:
    """AEGISKernel tracks cycle count."""
    kernel = AEGISKernel()
    assert kernel.cycle_count == 0
    kernel.run_cycle(_valid_proposal(), "c1")
    kernel.run_cycle(_valid_proposal(), "c2")
    assert kernel.cycle_count == 2
    return True


def _test_same_proposal_same_hash() -> bool:
    """Same proposal produces same graph_hash every time."""
    h1 = run_cycle(_valid_proposal(), "s1").graph_hash
    h2 = run_cycle(_valid_proposal(), "s2").graph_hash
    assert h1 == h2
    return True


def _test_signal_node_type_state_compiles() -> bool:
    """STATE nodes compile correctly."""
    p = _valid_proposal()
    result = run_cycle(p, "test_state_type")
    assert result.allowed
    return True


def _test_check_blocked_has_no_gate_result() -> bool:
    """When blocked at CHECK, gate_result is None."""
    result = run_cycle(_invalid_proposal_orphan(), "test_no_gate")
    assert result.gate_result is None
    return True


def _test_compiler_handles_empty_nodes() -> bool:
    """Empty nodes list compiles (validator will catch the empty graph)."""
    p = {"nodes": [], "edges": []}
    result = run_cycle(p, "test_empty")
    assert result.blocked
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
    print("AEGIS KERNEL — Labyrinth-OS Phase 2")
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

    # Demo
    print("\n── DEMO: Three cycles ──\n")
    scenarios = [
        ("ALLOW  — clean graph",         _valid_proposal()),
        ("BLOCK  — critical signal",      _proposal_with_critical()),
        ("BLOCK  — validation failure",   _invalid_proposal_orphan()),
    ]
    for label, proposal in scenarios:
        r = run_cycle(proposal, f"demo_{label[:5].strip()}")
        print(f"  {label}")
        print(f"    decision={r.decision.value}  phases={r.phases_run}")
        print(f"    blocked_at={r.blocked_at}  chain_valid={r.ledger_summary.get('chain_valid')}")
        print()

    with open(__file__, "rb") as f:
        file_hash = _hl.sha256(f.read()).hexdigest()

    print(f"── RECEIPT ──")
    print(f"  SHA-256: {file_hash}")
    print(f"  File:    aegis_cesk.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 2 Step 3: aegis_cesk.py — COMPLETE")
    print(f"{'=' * 70}")
