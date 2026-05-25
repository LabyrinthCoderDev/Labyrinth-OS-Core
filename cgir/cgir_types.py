"""
cgir_types.py — Labyrinth-OS / CGIR Phase 1
=============================================
Causal Graph Intermediate Representation — Core Types

Data definitions ONLY.
No logic. No validation. No behavior.
Only named, typed structures.

Every field is explicit. No default values that hide intent.
No optional fields that smuggle nullable state.

References:
  ARCHITECTURE.md  — Layer L10 (CGIR)
  INVARIANTS.md    — I1 Execution Closure, I7 Epistemic Containment
  spec/CGIR.md     — Node, Edge, Signal, Graph specifications
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional


# ─── PRIMITIVE TYPES ──────────────────────────────────────────────────────────
# Named aliases. Not just strings — named so mistakes are caught at read time.

NodeId   = str   # Unique node identifier within a graph
EdgeId   = str   # Unique edge identifier within a graph
SignalId = str   # Unique signal identifier within a graph


# ─── ENUMERATIONS ─────────────────────────────────────────────────────────────

@unique
class NodeType(str, Enum):
    """
    Exhaustive set of node types in a CGIR graph.
    String enum so values serialize directly to JSON without mapping.
    """
    STATE         = "STATE"          # Snapshot of CESK execution state
    EVENT_EDGE    = "EVENT_EDGE"     # State transition with invariant mask
    SIGNAL        = "SIGNAL"         # Annotated severity/confidence signal
    TIMED_EDGE    = "TIMED_EDGE"     # Transition with latency constraints
    INVARIANT     = "INVARIANT"      # Bound invariant rule (pass/fail/partial)
    HARDWARE      = "HARDWARE"       # Hardware register / MMIO / RoT binding


@unique
class InvariantStatus(str, Enum):
    """Status of an invariant binding check."""
    PASS    = "PASS"
    FAIL    = "FAIL"
    PARTIAL = "PARTIAL"


@unique
class Severity(str, Enum):
    """
    Signal severity levels. Integer ordering is meaningful:
    higher ordinal = higher severity = higher gate priority.
    """
    INFO     = "INFO"      # Informational annotation
    WARNING  = "WARNING"   # Elevated risk observed
    ERROR    = "ERROR"     # Significant risk or inconsistency
    CRITICAL = "CRITICAL"  # Immediate HARD_FAIL required


@unique
class GateDecision(str, Enum):
    """All possible Gate output values."""
    ALLOW    = "ALLOW"     # Execute as proposed
    BLOCK    = "BLOCK"     # Reject — do not execute


# ─── VALUE OBJECTS ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TimeRange:
    """
    A closed logical-time interval [start_time, end_time].
    Both bounds are inclusive. Logical time is a non-negative integer.
    """
    start_time: int   # inclusive lower bound, logical time
    end_time: int     # inclusive upper bound, logical time

    def __post_init__(self) -> None:
        # frozen=True prevents mutation — validation lives in cgir_validator.py.
        # This is intentionally empty: types carry no validation logic.
        pass

    def contains(self, t: int) -> bool:
        """Returns True if logical time t falls within this range."""
        return self.start_time <= t <= self.end_time


# ─── NODE TYPES ───────────────────────────────────────────────────────────────

@dataclass
class Node:
    """
    Base node structure. All node types share these fields.

    id            — unique within a graph, stable across replay
    node_type     — determines interpretation (StateNode, SignalNode, etc.)
    logical_time  — monotonically increasing sequence number (not wall-clock)
    metadata      — arbitrary per-node data; content validated per node_type
                    by cgir_validator.py, not here.
    """
    id: NodeId
    node_type: NodeType
    logical_time: int
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)


@dataclass
class StateNode(Node):
    """
    A snapshot of CESK execution state.

    state_root   — hash of the full CESK state at this point
    parent_state — NodeId of the prior StateNode (None for genesis)
    data_hash    — hash of any auxiliary state data
    """
    state_root: str = ""
    parent_state: Optional[NodeId] = None
    data_hash: str = ""

    def __post_init__(self) -> None:
        self.node_type = NodeType.STATE


@dataclass
class SignalNode(Node):
    """
    An annotated severity/confidence signal.

    Only the Council Resolver may produce SignalNodes that bind to CGIR edges.
    (Invariant I4: exactly one SignalNode per event cycle.)

    severity     — escalation level
    confidence   — float in [0.0, 1.0]
    category     — human-readable signal category string
    evidence_refs — NodeIds supporting this signal
    valid_for    — time range during which this signal is valid (Invariant I5)
    source       — originating sensor or watcher ("VECTOR", "WATCHER_A", etc.)
    emitted_by   — must be "COUNCIL" for CGIR-bound signals (Invariant I4)
    """
    severity: Severity = Severity.INFO
    confidence: float = 0.0
    category: str = ""
    evidence_refs: List[NodeId] = field(default_factory=list)
    valid_for: Optional[TimeRange] = None
    source: str = ""
    emitted_by: str = ""

    def __post_init__(self) -> None:
        self.node_type = NodeType.SIGNAL


# ─── EDGE TYPES ───────────────────────────────────────────────────────────────

@dataclass
class Edge:
    """
    A directed transition between two nodes.

    id               — unique within a graph
    from_id          — source NodeId
    to_id            — destination NodeId
    event_type       — semantic label for this transition
    invariant_mask   — list of invariant rule identifiers that must hold
    signal_binding   — SignalId of the SignalNode annotating this edge
                       (None only for edges not yet through Council)
    """
    id: EdgeId
    from_id: NodeId
    to_id: NodeId
    event_type: str
    invariant_mask: List[str] = field(default_factory=list)
    signal_binding: Optional[SignalId] = None


@dataclass
class TimedEdge(Edge):
    """
    An edge with explicit latency constraints.

    expected_latency_ns — nominal expected execution time in nanoseconds
    max_latency_ns      — hard ceiling; violation triggers Gate rejection
    observed_latency_ns — filled in post-execution by AEGIS
    """
    expected_latency_ns: int = 0
    max_latency_ns: int = 0
    observed_latency_ns: Optional[int] = None


# ─── INVARIANT BINDING ────────────────────────────────────────────────────────

@dataclass
class InvariantBinding:
    """
    A record of an invariant check bound to a CGIR edge.

    rule         — canonical invariant rule identifier (e.g. "I1", "I3")
    scope        — which subsystem the check covers
    status       — current evaluation result
    failure_code — populated when status == FAIL
    """
    rule: str
    scope: str
    status: InvariantStatus = InvariantStatus.PASS
    failure_code: Optional[str] = None


# ─── VALIDATION ERROR ─────────────────────────────────────────────────────────

@dataclass
class ValidationError:
    """
    Structured error from cgir_validator.py.

    error_type — machine-readable category (e.g. "ORPHAN_NODE")
    message    — human-readable description
    node_id    — relevant node, if applicable
    edge_id    — relevant edge, if applicable
    field      — specific field that failed, if applicable
    """
    error_type: str
    message: str
    node_id: Optional[NodeId] = None
    edge_id: Optional[EdgeId] = None
    field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            **({"node_id": self.node_id} if self.node_id else {}),
            **({"edge_id": self.edge_id} if self.edge_id else {}),
            **({"field": self.field} if self.field else {}),
        }


@dataclass
class ValidationResult:
    """
    Output of cgir_validator.validate(graph).
    valid is True only when errors is empty.
    """
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
        }


# ─── GATE RESULT ──────────────────────────────────────────────────────────────

@dataclass
class BlockReason(Enum):
    """Structured reason for a gate BLOCK decision.
    
    Replaces free-form string matching in downstream code (e.g. cgir_guardian_bridge.py).
    Use this instead of parsing reason strings like "CRITICAL" in reason.
    
    PROTOTYPE NOTE: cgir_guardian_bridge.py still uses string matching for now.
    ROADMAP: replace guardian bridge string matching with this enum field.
    """
    CRITICAL_SIGNAL    = "CRITICAL_SIGNAL"
    ERROR_SIGNAL       = "ERROR_SIGNAL"
    CONFIDENCE_FLOOR   = "CONFIDENCE_FLOOR"
    TAU_COLLAPSE       = "TAU_COLLAPSE"
    CHI_COLLAPSE       = "CHI_COLLAPSE"
    DRIFT_EXCEEDED     = "DRIFT_EXCEEDED"
    BETTI_CAP          = "BETTI_CAP"
    INVARIANT_VIOLATED = "INVARIANT_VIOLATED"
    NOT_PROMOTED       = "NOT_PROMOTED"
    UNKNOWN            = "UNKNOWN"


@dataclass
class GateResult:
    """
    Output of cgir_gate.evaluate(graph).

    decision     — ALLOW or BLOCK
    reason       — one-line explanation (required for BLOCK, optional for ALLOW)
    block_reason — structured reason enum (preferred over parsing reason string)
    
    Use block_reason for programmatic checks. Use reason for human-readable logs.
    Do not parse the reason string — use block_reason instead.
    """
    decision:     GateDecision
    reason:       str = ""
    block_reason: Optional[BlockReason] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
          "block_reason": self.block_reason.value if self.block_reason else None,
            "reason": self.reason,
        }


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_node_type_enum_values() -> bool:
    """NodeType enum has the correct string values."""
    assert NodeType.STATE.value == "STATE"
    assert NodeType.SIGNAL.value == "SIGNAL"
    assert NodeType.EVENT_EDGE.value == "EVENT_EDGE"
    assert NodeType.TIMED_EDGE.value == "TIMED_EDGE"
    assert NodeType.INVARIANT.value == "INVARIANT"
    assert NodeType.HARDWARE.value == "HARDWARE"
    return True


def _test_severity_enum_values() -> bool:
    """Severity enum has the correct string values."""
    assert Severity.INFO.value == "INFO"
    assert Severity.WARNING.value == "WARNING"
    assert Severity.ERROR.value == "ERROR"
    assert Severity.CRITICAL.value == "CRITICAL"
    return True


def _test_gate_decision_enum_values() -> bool:
    """GateDecision enum has exactly ALLOW and BLOCK."""
    assert len(GateDecision) == 2
    assert GateDecision.ALLOW.value == "ALLOW"
    assert GateDecision.BLOCK.value == "BLOCK"
    return True


def _test_time_range_contains_inclusive() -> bool:
    """TimeRange.contains is inclusive on both bounds."""
    tr = TimeRange(start_time=10, end_time=20)
    assert tr.contains(10) is True
    assert tr.contains(15) is True
    assert tr.contains(20) is True
    assert tr.contains(9) is False
    assert tr.contains(21) is False
    return True


def _test_time_range_is_frozen() -> bool:
    """TimeRange is immutable after creation."""
    tr = TimeRange(start_time=1, end_time=5)
    try:
        tr.start_time = 0  # type: ignore
        raise AssertionError("Should have raised FrozenInstanceError")
    except Exception as e:
        assert "cannot assign" in str(e).lower() or "frozen" in str(e).lower()
    return True


def _test_node_construction() -> bool:
    """Node can be constructed with all required fields."""
    n = Node(id="n1", node_type=NodeType.STATE, logical_time=0)
    assert n.id == "n1"
    assert n.node_type == NodeType.STATE
    assert n.logical_time == 0
    assert n.metadata == {}
    return True


def _test_node_metadata_isolated() -> bool:
    """Two Node instances do not share the same metadata dict."""
    n1 = Node(id="n1", node_type=NodeType.STATE, logical_time=0)
    n2 = Node(id="n2", node_type=NodeType.STATE, logical_time=1)
    n1.metadata["key"] = "value"
    assert "key" not in n2.metadata
    return True


def _test_state_node_sets_type() -> bool:
    """StateNode forces node_type to STATE regardless of input."""
    sn = StateNode(id="s1", node_type=NodeType.HARDWARE, logical_time=0)
    assert sn.node_type == NodeType.STATE
    return True


def _test_signal_node_sets_type() -> bool:
    """SignalNode forces node_type to SIGNAL regardless of input."""
    sig = SignalNode(id="sig1", node_type=NodeType.STATE, logical_time=5)
    assert sig.node_type == NodeType.SIGNAL
    return True


def _test_signal_node_confidence_default() -> bool:
    """SignalNode default confidence is 0.0."""
    sig = SignalNode(id="sig1", node_type=NodeType.SIGNAL, logical_time=0)
    assert sig.confidence == 0.0
    return True


def _test_edge_construction() -> bool:
    """Edge can be constructed with required fields."""
    e = Edge(id="e1", from_id="n1", to_id="n2", event_type="STEP")
    assert e.id == "e1"
    assert e.from_id == "n1"
    assert e.to_id == "n2"
    assert e.event_type == "STEP"
    assert e.invariant_mask == []
    assert e.signal_binding is None
    return True


def _test_timed_edge_inherits_edge() -> bool:
    """TimedEdge is an Edge."""
    te = TimedEdge(
        id="te1", from_id="n1", to_id="n2",
        event_type="TIMED_STEP",
        expected_latency_ns=1000, max_latency_ns=5000,
    )
    assert isinstance(te, Edge)
    assert te.expected_latency_ns == 1000
    assert te.max_latency_ns == 5000
    assert te.observed_latency_ns is None
    return True


def _test_invariant_binding_defaults() -> bool:
    """InvariantBinding defaults to PASS with no failure code."""
    ib = InvariantBinding(rule="I1", scope="aegis-cesk")
    assert ib.status == InvariantStatus.PASS
    assert ib.failure_code is None
    return True


def _test_validation_error_to_dict_minimal() -> bool:
    """ValidationError.to_dict omits None optional fields."""
    err = ValidationError(error_type="ORPHAN_NODE", message="Node n1 has no edges")
    d = err.to_dict()
    assert d["error_type"] == "ORPHAN_NODE"
    assert d["message"] == "Node n1 has no edges"
    assert "node_id" not in d
    assert "edge_id" not in d
    return True


def _test_validation_error_to_dict_full() -> bool:
    """ValidationError.to_dict includes non-None optional fields."""
    err = ValidationError(
        error_type="INVALID_REFERENCE",
        message="Edge references missing node",
        node_id="n99",
        edge_id="e1",
        field="to_id",
    )
    d = err.to_dict()
    assert d["node_id"] == "n99"
    assert d["edge_id"] == "e1"
    assert d["field"] == "to_id"
    return True


def _test_validation_result_valid() -> bool:
    """ValidationResult with no errors has valid=True."""
    result = ValidationResult(valid=True)
    d = result.to_dict()
    assert d["valid"] is True
    assert d["errors"] == []
    return True


def _test_validation_result_invalid() -> bool:
    """ValidationResult with errors has valid=False and serializes errors."""
    err = ValidationError(error_type="ORPHAN_NODE", message="test")
    result = ValidationResult(valid=False, errors=[err])
    d = result.to_dict()
    assert d["valid"] is False
    assert len(d["errors"]) == 1
    assert d["errors"][0]["error_type"] == "ORPHAN_NODE"
    return True


def _test_gate_result_allow() -> bool:
    """GateResult serializes ALLOW decision."""
    gr = GateResult(decision=GateDecision.ALLOW)
    d = gr.to_dict()
    assert d["decision"] == "ALLOW"
    assert d["reason"] == ""
    return True


def _test_gate_result_block_requires_reason() -> bool:
    """GateResult BLOCK with a reason serializes correctly."""
    gr = GateResult(decision=GateDecision.BLOCK, reason="CRITICAL signal present")
    d = gr.to_dict()
    assert d["decision"] == "BLOCK"
    assert d["reason"] == "CRITICAL signal present"
    return True


def _test_invariant_status_values() -> bool:
    """InvariantStatus has exactly three values."""
    assert len(InvariantStatus) == 3
    assert InvariantStatus.PASS.value == "PASS"
    assert InvariantStatus.FAIL.value == "FAIL"
    assert InvariantStatus.PARTIAL.value == "PARTIAL"
    return True


def _test_signal_node_evidence_refs_isolated() -> bool:
    """Two SignalNode instances do not share the same evidence_refs list."""
    s1 = SignalNode(id="s1", node_type=NodeType.SIGNAL, logical_time=0)
    s2 = SignalNode(id="s2", node_type=NodeType.SIGNAL, logical_time=1)
    s1.evidence_refs.append("n1")
    assert "n1" not in s2.evidence_refs
    return True


# ─── TEST RUNNER ──────────────────────────────────────────────────────────────

def run_tests() -> tuple[int, int, list]:
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
    print("=" * 70)
    print("CGIR TYPES — Labyrinth-OS Phase 1")
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

    # Receipt
    with open(__file__, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {file_hash}")
    print(f"  File:    cgir_types.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 1 Step 1: cgir_types.py — COMPLETE")
    print(f"{'=' * 70}")
