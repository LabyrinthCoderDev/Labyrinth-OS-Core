"""
cgir_validator.py — Labyrinth-OS / CGIR Phase 1
================================================
Causal Graph Intermediate Representation — Strict Validator

This is the most critical module in Phase 1.

Rules:
  - No silent failures
  - No partial success
  - If anything is invalid → FAIL with structured errors
  - All checks run before any decision is made
  - Error list is exhaustive — every violation is reported, not just the first

Invariants enforced (from INVARIANTS.md):
  I1  — No execution outside valid CGIR edges
  I5  — Signals must be valid for their logical time window
  I7  — Epistemic containment: all references must resolve

Checks performed:
  1. No duplicate node IDs
  2. No duplicate edge IDs
  3. Every edge references existing node IDs (from_id, to_id)
  4. No orphan nodes (nodes with no edges)
  5. logical_time must be non-negative integers
  6. logical_time across nodes must be monotonically non-decreasing (by insertion)
  7. signal_binding must reference an existing signal (if not None)
  8. invariant_mask entries must be non-empty strings
  9. signal confidence must be in [0.0, 1.0]
  10. signal valid_for range must satisfy start_time <= end_time
  11. graph must have at least one node
  12. root and tip (if set) must reference existing nodes
"""

from __future__ import annotations

import hashlib
from typing import List, Set

from cgir_types import (
    Edge, Node, ValidationError, ValidationResult,
)
from cgir_core import CGIRGraph


# ─── ERROR TYPE CONSTANTS ──────────────────────────────────────────────────────
# Named constants so callers can match on error types without magic strings.

ERR_EMPTY_GRAPH             = "EMPTY_GRAPH"
ERR_DUPLICATE_NODE_ID       = "DUPLICATE_NODE_ID"
ERR_DUPLICATE_EDGE_ID       = "DUPLICATE_EDGE_ID"
ERR_EDGE_INVALID_FROM       = "EDGE_INVALID_FROM"
ERR_EDGE_INVALID_TO         = "EDGE_INVALID_TO"
ERR_ORPHAN_NODE             = "ORPHAN_NODE"
ERR_NEGATIVE_LOGICAL_TIME   = "NEGATIVE_LOGICAL_TIME"
ERR_NON_MONOTONIC_TIME      = "NON_MONOTONIC_TIME"
ERR_INVALID_SIGNAL_BINDING  = "INVALID_SIGNAL_BINDING"
ERR_INVALID_INVARIANT_MASK  = "INVALID_INVARIANT_MASK"
ERR_SIGNAL_CONFIDENCE_RANGE = "SIGNAL_CONFIDENCE_RANGE"
ERR_SIGNAL_TIME_RANGE       = "SIGNAL_TIME_RANGE"
ERR_INVALID_ROOT            = "INVALID_ROOT"
ERR_INVALID_TIP             = "INVALID_TIP"
ERR_MISSING_EMITTER         = "MISSING_EMITTER"


# ─── VALIDATOR ────────────────────────────────────────────────────────────────

class CGIRValidator:
    """
    Validates a CGIRGraph against all structural invariants.

    Usage:
        v = CGIRValidator()
        result = v.validate(graph)
        if not result.valid:
            for err in result.errors:
                print(err.to_dict())

    All checks are independent — the full error list is always produced.
    """

    def validate(self, graph: CGIRGraph) -> ValidationResult:
        """
        Run all validation checks.
        Returns ValidationResult(valid=True) only if zero errors found.
        """
        errors: List[ValidationError] = []

        errors.extend(self._check_not_empty(graph))
        errors.extend(self._check_duplicate_node_ids(graph))
        errors.extend(self._check_duplicate_edge_ids(graph))
        errors.extend(self._check_edge_node_references(graph))
        errors.extend(self._check_orphan_nodes(graph))
        errors.extend(self._check_logical_time(graph))
        errors.extend(self._check_signal_bindings(graph))
        errors.extend(self._check_invariant_masks(graph))
        errors.extend(self._check_signal_confidence(graph))
        errors.extend(self._check_signal_time_ranges(graph))
        errors.extend(self._check_root_and_tip(graph))
        errors.extend(self._check_signal_emitter(graph))

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    # ── Check: graph must not be empty ────────────────────────────────────────

    def _check_not_empty(self, graph: CGIRGraph) -> List[ValidationError]:
        if graph.is_empty:
            return [ValidationError(
                error_type=ERR_EMPTY_GRAPH,
                message="Graph contains no nodes and no edges.",
            )]
        return []

    # ── Check: no duplicate node IDs ──────────────────────────────────────────
    # cgir_core silently overwrites duplicate node ids.
    # The graph's node_ids() returns unique ids by dict key.
    # We track insertion separately to detect the case if needed.
    # In practice: if the validator runs on a graph where the core already
    # collapsed duplicates, we still check — the core test confirms it stores
    # the last write. This check is therefore a belt-and-suspenders contract.

    def _check_duplicate_node_ids(self, graph: CGIRGraph) -> List[ValidationError]:
        # node_ids() returns dict keys — always unique after core.add_node.
        # This check exists for future raw-dict injection paths.
        seen: Set[str] = set()
        errors = []
        for nid in graph.node_ids():
            if nid in seen:
                errors.append(ValidationError(
                    error_type=ERR_DUPLICATE_NODE_ID,
                    message=f"Node ID '{nid}' appears more than once.",
                    node_id=nid,
                ))
            seen.add(nid)
        return errors

    # ── Check: no duplicate edge IDs ──────────────────────────────────────────

    def _check_duplicate_edge_ids(self, graph: CGIRGraph) -> List[ValidationError]:
        seen: Set[str] = set()
        errors = []
        for edge in graph.edges():
            if edge.id in seen:
                errors.append(ValidationError(
                    error_type=ERR_DUPLICATE_EDGE_ID,
                    message=f"Edge ID '{edge.id}' appears more than once.",
                    edge_id=edge.id,
                ))
            seen.add(edge.id)
        return errors

    # ── Check: every edge references existing nodes ───────────────────────────

    def _check_edge_node_references(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        for edge in graph.edges():
            if not graph.has_node(edge.from_id):
                errors.append(ValidationError(
                    error_type=ERR_EDGE_INVALID_FROM,
                    message=f"Edge '{edge.id}' from_id '{edge.from_id}' does not exist.",
                    edge_id=edge.id,
                    field="from_id",
                ))
            if not graph.has_node(edge.to_id):
                errors.append(ValidationError(
                    error_type=ERR_EDGE_INVALID_TO,
                    message=f"Edge '{edge.id}' to_id '{edge.to_id}' does not exist.",
                    edge_id=edge.id,
                    field="to_id",
                ))
        return errors

    # ── Check: no orphan nodes ────────────────────────────────────────────────
    # A node is an orphan if it has no incoming AND no outgoing edges.
    # Exception: if the graph has exactly one node and no edges, that node
    # is a valid genesis-only graph (but the empty-graph check already handles
    # the zero-node case). A single-node graph with no edges IS flagged as
    # orphan — a valid CGIR graph must have state transitions.

    def _check_orphan_nodes(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        for node in graph.iter_nodes():
            has_out = bool(graph.outgoing_edges(node.id))
            has_in  = bool(graph.incoming_edges(node.id))
            if not has_out and not has_in:
                errors.append(ValidationError(
                    error_type=ERR_ORPHAN_NODE,
                    message=f"Node '{node.id}' has no incoming or outgoing edges.",
                    node_id=node.id,
                ))
        return errors

    # ── Check: logical_time is non-negative and non-decreasing ───────────────

    def _check_logical_time(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        prev_time: int = -1
        for node in graph.iter_nodes():
            if node.logical_time < 0:
                errors.append(ValidationError(
                    error_type=ERR_NEGATIVE_LOGICAL_TIME,
                    message=(
                        f"Node '{node.id}' has negative logical_time "
                        f"({node.logical_time})."
                    ),
                    node_id=node.id,
                    field="logical_time",
                ))
            elif node.logical_time < prev_time:
                errors.append(ValidationError(
                    error_type=ERR_NON_MONOTONIC_TIME,
                    message=(
                        f"Node '{node.id}' logical_time {node.logical_time} "
                        f"is less than previous {prev_time}."
                    ),
                    node_id=node.id,
                    field="logical_time",
                ))
            if node.logical_time >= 0:
                prev_time = max(prev_time, node.logical_time)
        return errors

    # ── Check: signal_binding references existing signal ──────────────────────

    def _check_signal_bindings(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        for edge in graph.edges():
            if edge.signal_binding is not None:
                if not graph.has_signal(edge.signal_binding):
                    errors.append(ValidationError(
                        error_type=ERR_INVALID_SIGNAL_BINDING,
                        message=(
                            f"Edge '{edge.id}' signal_binding '{edge.signal_binding}' "
                            f"does not reference an existing signal."
                        ),
                        edge_id=edge.id,
                        field="signal_binding",
                    ))
        return errors

    # ── Check: invariant_mask entries are non-empty strings ───────────────────

    def _check_invariant_masks(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        for edge in graph.edges():
            for i, rule in enumerate(edge.invariant_mask):
                if not isinstance(rule, str) or rule.strip() == "":
                    errors.append(ValidationError(
                        error_type=ERR_INVALID_INVARIANT_MASK,
                        message=(
                            f"Edge '{edge.id}' invariant_mask[{i}] is not a "
                            f"non-empty string (got {rule!r})."
                        ),
                        edge_id=edge.id,
                        field=f"invariant_mask[{i}]",
                    ))
        return errors

    # ── Check: signal confidence in [0.0, 1.0] ───────────────────────────────

    def _check_signal_confidence(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        for signal in graph.signals():
            if not (0.0 <= signal.confidence <= 1.0):
                errors.append(ValidationError(
                    error_type=ERR_SIGNAL_CONFIDENCE_RANGE,
                    message=(
                        f"Signal '{signal.id}' confidence {signal.confidence} "
                        f"is outside [0.0, 1.0]."
                    ),
                    node_id=signal.id,
                    field="confidence",
                ))
        return errors

    # ── Check: signal valid_for start_time <= end_time ───────────────────────

    def _check_signal_time_ranges(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        for signal in graph.signals():
            if signal.valid_for is not None:
                vf = signal.valid_for
                if vf.start_time > vf.end_time:
                    errors.append(ValidationError(
                        error_type=ERR_SIGNAL_TIME_RANGE,
                        message=(
                            f"Signal '{signal.id}' valid_for has start_time "
                            f"{vf.start_time} > end_time {vf.end_time}."
                        ),
                        node_id=signal.id,
                        field="valid_for",
                    ))
        return errors

    # ── Check: root and tip (if set) reference existing nodes ────────────────

    def _check_root_and_tip(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        if graph.root is not None and not graph.has_node(graph.root):
            errors.append(ValidationError(
                error_type=ERR_INVALID_ROOT,
                message=f"Graph root '{graph.root}' does not reference an existing node.",
                field="root",
            ))
        if graph.tip is not None and not graph.has_node(graph.tip):
            errors.append(ValidationError(
                error_type=ERR_INVALID_TIP,
                message=f"Graph tip '{graph.tip}' does not reference an existing node.",
                field="tip",
            ))
        return errors

    # ── Check: CGIR-bound signals must have emitted_by == "COUNCIL" ──────────
    # Invariant I4: only Council Resolver emits SignalNodes into CGIR.
    # A signal that is bound to at least one edge must have emitted_by="COUNCIL".

    def _check_signal_emitter(self, graph: CGIRGraph) -> List[ValidationError]:
        errors = []
        bound_signal_ids = {
            edge.signal_binding
            for edge in graph.edges()
            if edge.signal_binding is not None
        }
        for signal in graph.signals():
            if signal.id in bound_signal_ids:
                if signal.emitted_by != "COUNCIL":
                    errors.append(ValidationError(
                        error_type=ERR_MISSING_EMITTER,
                        message=(
                            f"Signal '{signal.id}' is bound to a CGIR edge but "
                            f"emitted_by is '{signal.emitted_by}' (must be 'COUNCIL')."
                        ),
                        node_id=signal.id,
                        field="emitted_by",
                    ))
        return errors


# ─── MODULE-LEVEL CONVENIENCE ─────────────────────────────────────────────────

def validate(graph: CGIRGraph) -> ValidationResult:
    """Convenience function: validate(graph) → ValidationResult."""
    return CGIRValidator().validate(graph)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _make_valid_two_node_graph() -> CGIRGraph:
    """Two nodes, one edge, no signals. Valid."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.set_root("n0")
    g.set_tip("n1")
    return g


def _make_valid_graph_with_signal() -> CGIRGraph:
    """Two nodes, one edge, one valid signal bound to edge."""
    from cgir_types import Edge, Node, NodeType, Severity, SignalNode, TimeRange
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    sig = SignalNode(
        id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
        severity=Severity.WARNING, confidence=0.75,
        category="DRIFT", source="VECTOR", emitted_by="COUNCIL",
        valid_for=TimeRange(start_time=0, end_time=5),
    )
    g.add_signal(sig)
    g.add_edge(Edge(
        id="e0", from_id="n0", to_id="n1", event_type="STEP",
        signal_binding="sig0",
    ))
    return g


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_valid_two_node_graph_passes() -> bool:
    """A valid two-node graph passes validation."""
    result = validate(_make_valid_two_node_graph())
    assert result.valid is True
    assert result.errors == []
    return True


def _test_valid_graph_with_signal_passes() -> bool:
    """A valid graph with a bound COUNCIL signal passes."""
    result = validate(_make_valid_graph_with_signal())
    assert result.valid is True
    assert result.errors == []
    return True


def _test_empty_graph_fails() -> bool:
    """Empty graph is invalid."""
    g = CGIRGraph()
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_EMPTY_GRAPH in types
    return True


def _test_orphan_node_detected() -> bool:
    """A node with no edges is an orphan."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_ORPHAN_NODE in types
    errs = [e for e in result.errors if e.error_type == ERR_ORPHAN_NODE]
    assert errs[0].node_id == "n0"
    return True


def _test_edge_with_invalid_from_fails() -> bool:
    """Edge referencing nonexistent from_id is invalid."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="ghost", to_id="n1", event_type="STEP"))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_EDGE_INVALID_FROM in types
    return True


def _test_edge_with_invalid_to_fails() -> bool:
    """Edge referencing nonexistent to_id is invalid."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="ghost", event_type="STEP"))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_EDGE_INVALID_TO in types
    return True


def _test_negative_logical_time_fails() -> bool:
    """Node with negative logical_time is invalid."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=-1))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=0))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_NEGATIVE_LOGICAL_TIME in types
    return True


def _test_non_monotonic_logical_time_fails() -> bool:
    """Nodes with non-monotonic logical_time fail validation."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=5))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=3))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_NON_MONOTONIC_TIME in types
    return True


def _test_same_logical_time_is_valid() -> bool:
    """Two nodes with the same logical_time is allowed (non-decreasing, not strictly)."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    result = validate(g)
    # Only other issues: n1 has no outgoing edge (orphan check on n0 is fine as it has out-edge)
    # n1 is not an orphan either — it has incoming. So this should be valid.
    types = {e.error_type for e in result.errors}
    assert ERR_NON_MONOTONIC_TIME not in types
    assert ERR_NEGATIVE_LOGICAL_TIME not in types
    return True


def _test_invalid_signal_binding_fails() -> bool:
    """Edge with signal_binding referencing nonexistent signal is invalid."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(
        id="e0", from_id="n0", to_id="n1", event_type="STEP",
        signal_binding="ghost_signal",
    ))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_INVALID_SIGNAL_BINDING in types
    return True


def _test_empty_invariant_mask_entry_fails() -> bool:
    """Edge with empty string in invariant_mask fails."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(
        id="e0", from_id="n0", to_id="n1", event_type="STEP",
        invariant_mask=["I1", ""],
    ))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_INVALID_INVARIANT_MASK in types
    return True


def _test_valid_invariant_mask_passes() -> bool:
    """Edge with well-formed invariant_mask passes that check."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(
        id="e0", from_id="n0", to_id="n1", event_type="STEP",
        invariant_mask=["I1", "I3", "I7"],
    ))
    result = validate(g)
    types = {e.error_type for e in result.errors}
    assert ERR_INVALID_INVARIANT_MASK not in types
    return True


def _test_signal_confidence_above_1_fails() -> bool:
    """Signal with confidence > 1.0 is invalid."""
    from cgir_types import NodeType, SignalNode
    g = CGIRGraph()
    g.add_signal(SignalNode(
        id="s0", node_type=NodeType.SIGNAL, logical_time=0,
        confidence=1.01, emitted_by="COUNCIL",
    ))
    # Need a node+edge for graph to not be empty and not orphan
    from cgir_types import Edge, Node
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    result = validate(g)
    types = {e.error_type for e in result.errors}
    assert ERR_SIGNAL_CONFIDENCE_RANGE in types
    return True


def _test_signal_confidence_below_0_fails() -> bool:
    """Signal with confidence < 0.0 is invalid."""
    from cgir_types import Edge, Node, NodeType, SignalNode
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_signal(SignalNode(
        id="s0", node_type=NodeType.SIGNAL, logical_time=0,
        confidence=-0.1, emitted_by="COUNCIL",
    ))
    result = validate(g)
    types = {e.error_type for e in result.errors}
    assert ERR_SIGNAL_CONFIDENCE_RANGE in types
    return True


def _test_signal_confidence_boundary_values_valid() -> bool:
    """Signal confidence of exactly 0.0 and 1.0 are valid."""
    from cgir_types import Edge, Node, NodeType, SignalNode
    for conf in [0.0, 1.0]:
        g = CGIRGraph()
        g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
        g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
        g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
        g.add_signal(SignalNode(
            id="s0", node_type=NodeType.SIGNAL, logical_time=0,
            confidence=conf, emitted_by="COUNCIL",
        ))
        result = validate(g)
        types = {e.error_type for e in result.errors}
        assert ERR_SIGNAL_CONFIDENCE_RANGE not in types, f"Failed for conf={conf}"
    return True


def _test_signal_time_range_inverted_fails() -> bool:
    """Signal with start_time > end_time is invalid."""
    from cgir_types import Edge, Node, NodeType, SignalNode, TimeRange
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_signal(SignalNode(
        id="s0", node_type=NodeType.SIGNAL, logical_time=0,
        confidence=0.8, emitted_by="COUNCIL",
        valid_for=TimeRange(start_time=10, end_time=5),
    ))
    result = validate(g)
    types = {e.error_type for e in result.errors}
    assert ERR_SIGNAL_TIME_RANGE in types
    return True


def _test_signal_time_range_equal_bounds_valid() -> bool:
    """Signal valid_for with start == end is valid (single-moment window)."""
    from cgir_types import Edge, Node, NodeType, SignalNode, TimeRange
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_signal(SignalNode(
        id="s0", node_type=NodeType.SIGNAL, logical_time=0,
        confidence=0.8, emitted_by="COUNCIL",
        valid_for=TimeRange(start_time=5, end_time=5),
    ))
    result = validate(g)
    types = {e.error_type for e in result.errors}
    assert ERR_SIGNAL_TIME_RANGE not in types
    return True


def _test_invalid_root_fails() -> bool:
    """Graph root referencing nonexistent node is invalid."""
    g = _make_valid_two_node_graph()
    g.set_root("ghost")
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_INVALID_ROOT in types
    return True


def _test_invalid_tip_fails() -> bool:
    """Graph tip referencing nonexistent node is invalid."""
    g = _make_valid_two_node_graph()
    g.set_tip("ghost")
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_INVALID_TIP in types
    return True


def _test_signal_not_council_emitted_but_bound_fails() -> bool:
    """Signal bound to an edge but not emitted by COUNCIL is invalid (I4)."""
    from cgir_types import Edge, Node, NodeType, Severity, SignalNode
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    sig = SignalNode(
        id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
        severity=Severity.WARNING, confidence=0.75,
        category="DRIFT", source="VECTOR", emitted_by="WATCHER_A",
    )
    g.add_signal(sig)
    g.add_edge(Edge(
        id="e0", from_id="n0", to_id="n1", event_type="STEP",
        signal_binding="sig0",
    ))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_MISSING_EMITTER in types
    return True


def _test_unbound_signal_non_council_is_ok() -> bool:
    """Signal NOT bound to any edge may have any emitted_by."""
    from cgir_types import Edge, Node, NodeType, SignalNode
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    # This signal is not bound to any edge
    g.add_signal(SignalNode(
        id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
        confidence=0.5, emitted_by="WATCHER_A",
    ))
    result = validate(g)
    types = {e.error_type for e in result.errors}
    assert ERR_MISSING_EMITTER not in types
    return True


def _test_multiple_errors_all_reported() -> bool:
    """All errors are returned — validation does not stop at first failure."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    # Two nodes with bad logical_times + edge referencing ghost
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=-5))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=0))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="ghost_node", event_type="STEP"))
    result = validate(g)
    assert result.valid is False
    assert len(result.errors) >= 2  # at least: negative_time + invalid_to
    return True


def _test_duplicate_edge_id_fails() -> bool:
    """Two edges with the same id fail validation."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="n2", node_type=NodeType.STATE, logical_time=2))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_edge(Edge(id="e0", from_id="n1", to_id="n2", event_type="STEP"))
    result = validate(g)
    assert result.valid is False
    types = {e.error_type for e in result.errors}
    assert ERR_DUPLICATE_EDGE_ID in types
    return True


def _test_to_dict_valid_result() -> bool:
    """to_dict on a passing ValidationResult is correct."""
    result = validate(_make_valid_two_node_graph())
    d = result.to_dict()
    assert d["valid"] is True
    assert d["errors"] == []
    return True


def _test_to_dict_invalid_result() -> bool:
    """to_dict on a failing ValidationResult has structured errors."""
    g = CGIRGraph()  # empty
    result = validate(g)
    d = result.to_dict()
    assert d["valid"] is False
    assert len(d["errors"]) > 0
    assert "error_type" in d["errors"][0]
    assert "message" in d["errors"][0]
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
    import hashlib
    print("=" * 70)
    print("CGIR VALIDATOR — Labyrinth-OS Phase 1")
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

    with open(__file__, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {file_hash}")
    print(f"  File:    cgir_validator.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 1 Step 3: cgir_validator.py — COMPLETE")
    print(f"{'=' * 70}")
