"""
cgir_core.py — Labyrinth-OS / CGIR Phase 1
===========================================
Causal Graph Intermediate Representation — Graph Container

Raw container ONLY.
No validation. No invariant enforcement. No logic.

This module holds nodes, edges, and signals.
It does not know if they are correct.
That is cgir_validator.py's job.

The graph is a directed structure.
Ordering within each collection is insertion order.
Canonical ordering for hashing lives in cgir_determinism.py.

References:
  ARCHITECTURE.md  — Layer L10 (CGIR), CGIRGraph
  spec/CGIR.md     — CGIRGraph: nodes, edges, signals, root, tip
"""

from __future__ import annotations

import hashlib
from typing import Dict, Iterator, List, Optional

from cgir_types import (
    Edge, EdgeId, Node, NodeId, SignalId, SignalNode,
    ValidationError,
)


# ─── CGIR GRAPH ───────────────────────────────────────────────────────────────

class CGIRGraph:
    """
    Raw container for a CGIR graph.

    Holds:
      - nodes   : Dict[NodeId, Node]
      - edges   : List[Edge]  (insertion order)
      - signals : Dict[SignalId, SignalNode]
      - root    : NodeId of the initial StateNode (set explicitly)
      - tip     : NodeId of the current (most recent) StateNode (set explicitly)

    Does NOT validate. Does NOT enforce. Raw storage only.
    """

    def __init__(self) -> None:
        self._nodes: Dict[NodeId, Node] = {}
        self._edges: List[Edge] = []
        self._signals: Dict[SignalId, SignalNode] = {}
        self._root: Optional[NodeId] = None
        self._tip: Optional[NodeId] = None

    # ── Write ──────────────────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        """
        Add a node to the graph.
        If a node with the same id already exists, it is overwritten.
        Validation of duplicates is cgir_validator.py's responsibility.
        """
        self._nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        """
        Append an edge to the graph.
        Duplicate edges (same id) are NOT deduplicated here.
        Validation is cgir_validator.py's responsibility.
        """
        self._edges.append(edge)

    def add_signal(self, signal: SignalNode) -> None:
        """
        Add a signal node to the graph.
        Signals are stored separately from other nodes for fast lookup
        during edge signal_binding resolution.
        """
        self._signals[signal.id] = signal

    def set_root(self, node_id: NodeId) -> None:
        """Set the root (genesis) StateNode of the graph."""
        self._root = node_id

    def set_tip(self, node_id: NodeId) -> None:
        """Set the tip (current) StateNode of the graph."""
        self._tip = node_id

    # ── Read ───────────────────────────────────────────────────────────────

    def get_node(self, node_id: NodeId) -> Optional[Node]:
        """Return node by id, or None if not present."""
        return self._nodes.get(node_id)

    def get_signal(self, signal_id: SignalId) -> Optional[SignalNode]:
        """Return signal by id, or None if not present."""
        return self._signals.get(signal_id)

    def get_edge_by_id(self, edge_id: str) -> Optional[Edge]:
        """Return first edge with matching id, or None."""
        for edge in self._edges:
            if edge.id == edge_id:
                return edge
        return None

    def has_node(self, node_id: NodeId) -> bool:
        """Return True if node_id is in the graph."""
        return node_id in self._nodes

    def has_signal(self, signal_id: SignalId) -> bool:
        """Return True if signal_id is in the graph."""
        return signal_id in self._signals

    # ── Traversal ──────────────────────────────────────────────────────────

    def nodes(self) -> List[Node]:
        """Return all nodes in insertion order."""
        return list(self._nodes.values())

    def edges(self) -> List[Edge]:
        """Return all edges in insertion order."""
        return list(self._edges)

    def signals(self) -> List[SignalNode]:
        """Return all signals in insertion order (by insertion into dict)."""
        return list(self._signals.values())

    def outgoing_edges(self, node_id: NodeId) -> List[Edge]:
        """Return all edges whose from_id matches node_id."""
        return [e for e in self._edges if e.from_id == node_id]

    def incoming_edges(self, node_id: NodeId) -> List[Edge]:
        """Return all edges whose to_id matches node_id."""
        return [e for e in self._edges if e.to_id == node_id]

    def node_ids(self) -> List[NodeId]:
        """Return all node ids in insertion order."""
        return list(self._nodes.keys())

    def signal_ids(self) -> List[SignalId]:
        """Return all signal ids in insertion order."""
        return list(self._signals.keys())

    def iter_nodes(self) -> Iterator[Node]:
        """Iterate over all nodes."""
        return iter(self._nodes.values())

    def iter_edges(self) -> Iterator[Edge]:
        """Iterate over all edges."""
        return iter(self._edges)

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def root(self) -> Optional[NodeId]:
        return self._root

    @property
    def tip(self) -> Optional[NodeId]:
        return self._tip

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def signal_count(self) -> int:
        return len(self._signals)

    @property
    def is_empty(self) -> bool:
        return self.node_count == 0 and self.edge_count == 0


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _build_minimal_graph() -> CGIRGraph:
    """Helper: one node, no edges, no signals."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    return g


def _build_two_node_graph() -> CGIRGraph:
    """Helper: two nodes, one edge, no signals."""
    from cgir_types import Node, NodeType, Edge
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    return g


def _test_empty_graph_is_empty() -> bool:
    """New graph has zero nodes, edges, signals."""
    g = CGIRGraph()
    assert g.is_empty is True
    assert g.node_count == 0
    assert g.edge_count == 0
    assert g.signal_count == 0
    assert g.root is None
    assert g.tip is None
    return True


def _test_add_node_stores_it() -> bool:
    """add_node makes node retrievable via get_node."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    n = Node(id="n1", node_type=NodeType.STATE, logical_time=0)
    g.add_node(n)
    assert g.get_node("n1") is n
    assert g.has_node("n1") is True
    assert g.node_count == 1
    return True


def _test_add_node_overwrites_duplicate_id() -> bool:
    """add_node with existing id silently overwrites (no validation here)."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    n1 = Node(id="n1", node_type=NodeType.STATE, logical_time=0)
    n2 = Node(id="n1", node_type=NodeType.STATE, logical_time=99)
    g.add_node(n1)
    g.add_node(n2)
    assert g.node_count == 1
    assert g.get_node("n1") is n2
    return True


def _test_add_edge_stores_it() -> bool:
    """add_edge makes edge retrievable via get_edge_by_id."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    e = Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP")
    g.add_edge(e)
    assert g.get_edge_by_id("e0") is e
    assert g.edge_count == 1
    return True


def _test_add_signal_stores_it() -> bool:
    """add_signal makes signal retrievable via get_signal."""
    from cgir_types import NodeType, Severity, SignalNode
    g = CGIRGraph()
    sig = SignalNode(
        id="sig0", node_type=NodeType.SIGNAL, logical_time=0,
        severity=Severity.WARNING, confidence=0.8,
        category="DRIFT", source="VECTOR", emitted_by="COUNCIL",
    )
    g.add_signal(sig)
    assert g.get_signal("sig0") is sig
    assert g.has_signal("sig0") is True
    assert g.signal_count == 1
    return True


def _test_set_root_and_tip() -> bool:
    """set_root and set_tip store the node ids."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.set_root("n0")
    g.set_tip("n1")
    assert g.root == "n0"
    assert g.tip == "n1"
    return True


def _test_set_root_does_not_validate_existence() -> bool:
    """set_root accepts any string — validation is cgir_validator's job."""
    g = CGIRGraph()
    g.set_root("nonexistent_node")
    assert g.root == "nonexistent_node"
    return True


def _test_get_node_missing_returns_none() -> bool:
    """get_node on a missing id returns None (not an exception)."""
    g = CGIRGraph()
    assert g.get_node("ghost") is None
    return True


def _test_get_signal_missing_returns_none() -> bool:
    """get_signal on a missing id returns None."""
    g = CGIRGraph()
    assert g.get_signal("ghost") is None
    return True


def _test_get_edge_by_id_missing_returns_none() -> bool:
    """get_edge_by_id on a missing id returns None."""
    g = CGIRGraph()
    assert g.get_edge_by_id("ghost") is None
    return True


def _test_has_node_false_for_missing() -> bool:
    """has_node returns False for a node not in the graph."""
    g = CGIRGraph()
    assert g.has_node("ghost") is False
    return True


def _test_nodes_returns_list() -> bool:
    """nodes() returns a list of all added nodes."""
    g = _build_two_node_graph()
    ns = g.nodes()
    assert len(ns) == 2
    ids = {n.id for n in ns}
    assert "n0" in ids and "n1" in ids
    return True


def _test_edges_returns_list() -> bool:
    """edges() returns a list of all added edges."""
    g = _build_two_node_graph()
    es = g.edges()
    assert len(es) == 1
    assert es[0].id == "e0"
    return True


def _test_outgoing_edges_filters_correctly() -> bool:
    """outgoing_edges returns only edges with matching from_id."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    for i in range(3):
        g.add_node(Node(id=f"n{i}", node_type=NodeType.STATE, logical_time=i))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    g.add_edge(Edge(id="e1", from_id="n0", to_id="n2", event_type="STEP"))
    g.add_edge(Edge(id="e2", from_id="n1", to_id="n2", event_type="STEP"))
    out_n0 = g.outgoing_edges("n0")
    assert len(out_n0) == 2
    assert all(e.from_id == "n0" for e in out_n0)
    out_n1 = g.outgoing_edges("n1")
    assert len(out_n1) == 1
    assert out_n1[0].id == "e2"
    return True


def _test_incoming_edges_filters_correctly() -> bool:
    """incoming_edges returns only edges with matching to_id."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    for i in range(3):
        g.add_node(Node(id=f"n{i}", node_type=NodeType.STATE, logical_time=i))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n2", event_type="STEP"))
    g.add_edge(Edge(id="e1", from_id="n1", to_id="n2", event_type="STEP"))
    inc_n2 = g.incoming_edges("n2")
    assert len(inc_n2) == 2
    assert all(e.to_id == "n2" for e in inc_n2)
    return True


def _test_node_ids_returns_all_ids() -> bool:
    """node_ids() returns a list of all node ids."""
    g = _build_two_node_graph()
    ids = g.node_ids()
    assert "n0" in ids
    assert "n1" in ids
    assert len(ids) == 2
    return True


def _test_signal_ids_returns_all_signal_ids() -> bool:
    """signal_ids() returns all signal ids."""
    from cgir_types import NodeType, SignalNode
    g = CGIRGraph()
    s0 = SignalNode(id="s0", node_type=NodeType.SIGNAL, logical_time=0)
    s1 = SignalNode(id="s1", node_type=NodeType.SIGNAL, logical_time=1)
    g.add_signal(s0)
    g.add_signal(s1)
    ids = g.signal_ids()
    assert "s0" in ids
    assert "s1" in ids
    assert len(ids) == 2
    return True


def _test_multiple_edges_same_from_id_all_stored() -> bool:
    """Multiple edges from the same node are all stored."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="n2", node_type=NodeType.STATE, logical_time=2))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="A"))
    g.add_edge(Edge(id="e1", from_id="n0", to_id="n2", event_type="B"))
    assert g.edge_count == 2
    return True


def _test_duplicate_edge_id_not_deduplicated() -> bool:
    """Duplicate edge ids are stored as separate entries (validator catches this)."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    e1 = Edge(id="e0", from_id="n0", to_id="n1", event_type="A")
    e2 = Edge(id="e0", from_id="n0", to_id="n1", event_type="B")
    g.add_edge(e1)
    g.add_edge(e2)
    assert g.edge_count == 2
    return True


def _test_outgoing_edges_empty_for_unknown_node() -> bool:
    """outgoing_edges for an unknown node_id returns empty list."""
    g = _build_minimal_graph()
    assert g.outgoing_edges("ghost") == []
    return True


def _test_incoming_edges_empty_for_unknown_node() -> bool:
    """incoming_edges for an unknown node_id returns empty list."""
    g = _build_minimal_graph()
    assert g.incoming_edges("ghost") == []
    return True


def _test_iter_nodes_covers_all() -> bool:
    """iter_nodes yields all nodes exactly once."""
    g = _build_two_node_graph()
    seen = {n.id for n in g.iter_nodes()}
    assert seen == {"n0", "n1"}
    return True


def _test_iter_edges_covers_all() -> bool:
    """iter_edges yields all edges exactly once."""
    g = _build_two_node_graph()
    seen = [e.id for e in g.iter_edges()]
    assert seen == ["e0"]
    return True


def _test_signals_list_is_copy() -> bool:
    """signals() returns a copy — modifying it does not affect the graph."""
    from cgir_types import NodeType, SignalNode
    g = CGIRGraph()
    s = SignalNode(id="s0", node_type=NodeType.SIGNAL, logical_time=0)
    g.add_signal(s)
    lst = g.signals()
    lst.clear()
    assert g.signal_count == 1
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
    print("CGIR CORE — Labyrinth-OS Phase 1")
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
    print(f"  File:    cgir_core.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 1 Step 2: cgir_core.py — COMPLETE")
    print(f"{'=' * 70}")
