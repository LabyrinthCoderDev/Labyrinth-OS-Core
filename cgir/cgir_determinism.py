"""
cgir_determinism.py — Labyrinth-OS / CGIR Phase 1
==================================================
Causal Graph Intermediate Representation — Determinism Module

Canonical ordering, stable serialization, stable hashing.

Guarantees:
  - Same graph → same canonical form → same hash. Always.
  - No randomness.
  - No environment-dependent behavior.
  - No unordered structures in output.

Ordering rules:
  - Nodes: sorted by (logical_time ASC, id ASC)
  - Edges: sorted by (from_id ASC, to_id ASC, id ASC)
  - Signals: sorted by (logical_time ASC, id ASC)
  - Within lists: all sort keys are strings or integers — no floats in keys.

Serialization:
  - JSON with sorted keys at every level.
  - No pretty-printing (no whitespace variation).
  - None fields excluded from output.
  - Enum values serialized as their string values.

Hashing:
  - SHA-256 of the canonical JSON bytes (UTF-8).
  - Returns lowercase hex string (64 chars).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from cgir_types import Edge, Node, SignalNode
from cgir_core import CGIRGraph


# ─── CANONICAL SERIALIZERS ────────────────────────────────────────────────────

def _node_to_dict(node: Node) -> Dict[str, Any]:
    """Serialize a Node to a canonical dict. None fields omitted."""
    d: Dict[str, Any] = {
        "id": node.id,
        "node_type": node.node_type.value,
        "logical_time": node.logical_time,
    }
    if node.metadata:
        # Sort metadata keys for determinism
        d["metadata"] = {k: node.metadata[k] for k in sorted(node.metadata.keys())}
    return d


def _edge_to_dict(edge: Edge) -> Dict[str, Any]:
    """Serialize an Edge to a canonical dict. None fields omitted."""
    d: Dict[str, Any] = {
        "id": edge.id,
        "from_id": edge.from_id,
        "to_id": edge.to_id,
        "event_type": edge.event_type,
        "invariant_mask": sorted(edge.invariant_mask),  # sorted for determinism
    }
    if edge.signal_binding is not None:
        d["signal_binding"] = edge.signal_binding
    return d


def _signal_to_dict(signal: SignalNode) -> Dict[str, Any]:
    """Serialize a SignalNode to a canonical dict. None fields omitted."""
    d: Dict[str, Any] = {
        "id": signal.id,
        "node_type": signal.node_type.value,
        "logical_time": signal.logical_time,
        "severity": signal.severity.value,
        "confidence": signal.confidence,
        "category": signal.category,
        "evidence_refs": sorted(signal.evidence_refs),  # sorted for determinism
        "source": signal.source,
        "emitted_by": signal.emitted_by,
    }
    if signal.valid_for is not None:
        d["valid_for"] = {
            "start_time": signal.valid_for.start_time,
            "end_time": signal.valid_for.end_time,
        }
    if signal.metadata:
        d["metadata"] = {k: signal.metadata[k] for k in sorted(signal.metadata.keys())}
    return d


# ─── CANONICAL ORDERING ───────────────────────────────────────────────────────

def canonical_nodes(graph: CGIRGraph) -> List[Node]:
    """
    Return nodes in canonical order: (logical_time ASC, id ASC).
    Deterministic for any graph regardless of insertion order.
    """
    return sorted(graph.nodes(), key=lambda n: (n.logical_time, n.id))


def canonical_edges(graph: CGIRGraph) -> List[Edge]:
    """
    Return edges in canonical order: (from_id ASC, to_id ASC, id ASC).
    """
    return sorted(graph.edges(), key=lambda e: (e.from_id, e.to_id, e.id))


def canonical_signals(graph: CGIRGraph) -> List[SignalNode]:
    """
    Return signals in canonical order: (logical_time ASC, id ASC).
    """
    return sorted(graph.signals(), key=lambda s: (s.logical_time, s.id))


# ─── CANONICAL FORM ───────────────────────────────────────────────────────────

def canonical_form(graph: CGIRGraph) -> Dict[str, Any]:
    """
    Produce a canonical dict representation of the graph.

    Structure:
    {
      "nodes":   [ {...}, ... ]   # canonical order
      "edges":   [ {...}, ... ]   # canonical order
      "signals": [ {...}, ... ]   # canonical order
      "root":    "..." | null
      "tip":     "..." | null
    }

    This dict is the input to stable_serialize().
    """
    form: Dict[str, Any] = {
        "nodes":   [_node_to_dict(n) for n in canonical_nodes(graph)],
        "edges":   [_edge_to_dict(e) for e in canonical_edges(graph)],
        "signals": [_signal_to_dict(s) for s in canonical_signals(graph)],
    }
    # root and tip are explicitly included even if None — their absence
    # would make two graphs with different root/tip look identical.
    form["root"] = graph.root
    form["tip"]  = graph.tip
    return form


# ─── STABLE SERIALIZATION ─────────────────────────────────────────────────────

def stable_serialize(graph: CGIRGraph) -> bytes:
    """
    Produce a stable, deterministic UTF-8 JSON byte string for the graph.

    - sort_keys=True at every level
    - No whitespace (separators=(',', ':'))
    - Same graph → same bytes. Always.
    """
    form = canonical_form(graph)
    return json.dumps(form, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


# ─── STABLE HASH ──────────────────────────────────────────────────────────────

def stable_hash(graph: CGIRGraph) -> str:
    """
    SHA-256 of the stable serialization.
    Returns 64-character lowercase hex string.
    Same graph → same hash. Always.
    """
    return hashlib.sha256(stable_serialize(graph)).hexdigest()


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _build_graph_ab() -> CGIRGraph:
    """Graph: n_a → n_b (insertion order a, b)."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n_a", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n_b", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n_a", to_id="n_b", event_type="STEP"))
    return g


def _build_graph_ba() -> CGIRGraph:
    """Graph: n_a → n_b (insertion order b, a — reversed)."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n_b", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="n_a", node_type=NodeType.STATE, logical_time=0))
    g.add_edge(Edge(id="e0", from_id="n_a", to_id="n_b", event_type="STEP"))
    return g


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_canonical_nodes_sorted_by_time_then_id() -> bool:
    """canonical_nodes sorts by (logical_time, id)."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    # Insert in reverse order
    g.add_node(Node(id="z", node_type=NodeType.STATE, logical_time=2))
    g.add_node(Node(id="a", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="m", node_type=NodeType.STATE, logical_time=1))
    ordered = canonical_nodes(g)
    assert [n.id for n in ordered] == ["a", "m", "z"]
    return True


def _test_canonical_nodes_tiebreak_by_id() -> bool:
    """canonical_nodes breaks ties at same logical_time by id."""
    from cgir_types import Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="z", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="a", node_type=NodeType.STATE, logical_time=0))
    ordered = canonical_nodes(g)
    assert ordered[0].id == "a"
    assert ordered[1].id == "z"
    return True


def _test_canonical_edges_sorted() -> bool:
    """canonical_edges sorts by (from_id, to_id, id)."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="n2", node_type=NodeType.STATE, logical_time=2))
    # Insert in non-canonical order
    g.add_edge(Edge(id="e2", from_id="n1", to_id="n2", event_type="B"))
    g.add_edge(Edge(id="e1", from_id="n0", to_id="n2", event_type="A"))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="A"))
    ordered = canonical_edges(g)
    assert [e.id for e in ordered] == ["e0", "e1", "e2"]
    return True


def _test_canonical_signals_sorted_by_time_then_id() -> bool:
    """canonical_signals sorts by (logical_time, id)."""
    from cgir_types import NodeType, SignalNode
    g = CGIRGraph()
    g.add_signal(SignalNode(id="s_z", node_type=NodeType.SIGNAL, logical_time=5))
    g.add_signal(SignalNode(id="s_a", node_type=NodeType.SIGNAL, logical_time=0))
    g.add_signal(SignalNode(id="s_m", node_type=NodeType.SIGNAL, logical_time=3))
    ordered = canonical_signals(g)
    assert [s.id for s in ordered] == ["s_a", "s_m", "s_z"]
    return True


def _test_same_graph_same_hash() -> bool:
    """Same graph produces the same hash every time."""
    g = _build_graph_ab()
    h1 = stable_hash(g)
    h2 = stable_hash(g)
    assert h1 == h2
    assert len(h1) == 64
    return True


def _test_insertion_order_independent_hash() -> bool:
    """Two graphs with same data but different insertion order hash identically."""
    g_ab = _build_graph_ab()
    g_ba = _build_graph_ba()
    assert stable_hash(g_ab) == stable_hash(g_ba)
    return True


def _test_different_graph_different_hash() -> bool:
    """Two structurally different graphs produce different hashes."""
    from cgir_types import Edge, Node, NodeType
    g1 = _build_graph_ab()
    g2 = CGIRGraph()
    g2.add_node(Node(id="n_x", node_type=NodeType.STATE, logical_time=0))
    g2.add_node(Node(id="n_y", node_type=NodeType.STATE, logical_time=1))
    g2.add_edge(Edge(id="e0", from_id="n_x", to_id="n_y", event_type="STEP"))
    assert stable_hash(g1) != stable_hash(g2)
    return True


def _test_root_tip_included_in_hash() -> bool:
    """Changing root or tip changes the hash."""
    g1 = _build_graph_ab()
    g1.set_root("n_a")
    g2 = _build_graph_ab()
    g2.set_root("n_b")
    assert stable_hash(g1) != stable_hash(g2)
    return True


def _test_stable_serialize_returns_bytes() -> bool:
    """stable_serialize returns bytes."""
    g = _build_graph_ab()
    result = stable_serialize(g)
    assert isinstance(result, bytes)
    return True


def _test_stable_serialize_is_valid_json() -> bool:
    """stable_serialize output is valid JSON."""
    import json as _json
    g = _build_graph_ab()
    raw = stable_serialize(g)
    parsed = _json.loads(raw)
    assert isinstance(parsed, dict)
    assert "nodes" in parsed
    assert "edges" in parsed
    assert "signals" in parsed
    return True


def _test_stable_serialize_sorted_keys() -> bool:
    """stable_serialize output has sorted keys at every level."""
    import json as _json
    g = _build_graph_ab()
    raw = stable_serialize(g).decode("utf-8")
    # Top-level keys must appear in sorted order
    parsed = _json.loads(raw)
    top_keys = list(parsed.keys())
    assert top_keys == sorted(top_keys), f"Top keys not sorted: {top_keys}"
    return True


def _test_stable_serialize_no_whitespace() -> bool:
    """stable_serialize contains no spaces or newlines."""
    g = _build_graph_ab()
    raw = stable_serialize(g).decode("utf-8")
    assert " " not in raw
    assert "\n" not in raw
    return True


def _test_canonical_form_structure() -> bool:
    """canonical_form has nodes, edges, signals, root, tip keys."""
    g = _build_graph_ab()
    g.set_root("n_a")
    g.set_tip("n_b")
    form = canonical_form(g)
    assert "nodes" in form
    assert "edges" in form
    assert "signals" in form
    assert "root" in form
    assert "tip" in form
    assert form["root"] == "n_a"
    assert form["tip"] == "n_b"
    return True


def _test_canonical_form_null_root_tip() -> bool:
    """canonical_form includes root=null and tip=null when not set."""
    g = _build_graph_ab()
    form = canonical_form(g)
    assert form["root"] is None
    assert form["tip"] is None
    return True


def _test_hash_is_64_hex_chars() -> bool:
    """stable_hash always returns 64 lowercase hex characters."""
    g = _build_graph_ab()
    h = stable_hash(g)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    return True


def _test_invariant_mask_order_does_not_affect_hash() -> bool:
    """Two edges with same invariant_mask in different order produce same hash."""
    from cgir_types import Edge, Node, NodeType
    g1 = CGIRGraph()
    g1.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g1.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g1.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                     event_type="STEP", invariant_mask=["I1", "I3", "I7"]))
    g2 = CGIRGraph()
    g2.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g2.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g2.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                     event_type="STEP", invariant_mask=["I7", "I1", "I3"]))
    assert stable_hash(g1) == stable_hash(g2)
    return True


def _test_evidence_refs_order_does_not_affect_hash() -> bool:
    """Signal evidence_refs in different insertion order produce same hash."""
    from cgir_types import Edge, Node, NodeType, SignalNode
    def make(refs):
        g = CGIRGraph()
        g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
        g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
        g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
        g.add_signal(SignalNode(
            id="s0", node_type=NodeType.SIGNAL, logical_time=0,
            confidence=0.8, evidence_refs=refs, emitted_by="COUNCIL",
        ))
        return g
    g1 = make(["n_a", "n_b", "n_c"])
    g2 = make(["n_c", "n_a", "n_b"])
    assert stable_hash(g1) == stable_hash(g2)
    return True


def _test_metadata_key_order_does_not_affect_hash() -> bool:
    """Node metadata with different key insertion order produces same hash."""
    from cgir_types import Edge, Node, NodeType
    def make(meta):
        g = CGIRGraph()
        g.add_node(Node(id="n0", node_type=NodeType.STATE,
                        logical_time=0, metadata=meta))
        g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
        g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
        return g
    g1 = make({"z": 1, "a": 2})
    g2 = make({"a": 2, "z": 1})
    assert stable_hash(g1) == stable_hash(g2)
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
    print("=" * 70)
    print("CGIR DETERMINISM — Labyrinth-OS Phase 1")
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
    print(f"  File:    cgir_determinism.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 1 Step 4: cgir_determinism.py — COMPLETE")
    print(f"{'=' * 70}")
