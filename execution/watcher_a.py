"""
watcher_a.py — Labyrinth-OS / Epistemic Layer
==============================================
Watcher-A — Internal Consistency Auditor

Watcher-A performs internal consistency checks on a CGIRGraph.
It is independent of Watcher-B. It cannot see Watcher-B's output.
It cannot write to the graph or the ledger.

Watcher-A checks:
  1. Temporal consistency — logical_time ordering is sound
  2. Signal binding coherence — every bound signal is valid for its edge
  3. Invariant mask completeness — required invariants are present
  4. Chain integrity — graph has a path from root to tip
  5. Confidence plausibility — signal confidence is internally consistent

Watcher-A produces a WatcherReport. The Council Resolver reads both
Watcher-A and Watcher-B reports and merges them into one SignalNode.

Rules:
  - READ ONLY. No mutation of graph, ledger, or any external state.
  - No communication with Watcher-B (independence requirement).
  - Fail closed: any internal error → report with AUDIT_ERROR finding.
  - Deterministic: same graph → same report.

References:
  ARCHITECTURE.md  — L3 Watcher-A (internal consistency)
  INVARIANTS.md    — I3 VECTOR read-only, I4 Council emits SignalNode
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import List, Optional

from cgir_types import Node, NodeType, Severity
from cgir_core import CGIRGraph
from cgir_determinism import stable_hash


# ─── FINDING ──────────────────────────────────────────────────────────────────

@unique
class FindingLevel(str, Enum):
    OK      = "OK"
    WARN    = "WARN"
    FAIL    = "FAIL"
    ERROR   = "ERROR"     # internal auditor error (not graph error)


@dataclass(frozen=True)
class Finding:
    check: str
    level: FindingLevel
    detail: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


# ─── WATCHER REPORT ───────────────────────────────────────────────────────────

@dataclass
class WatcherReport:
    """
    Output of Watcher-A or Watcher-B audit.

    graph_hash  — stable hash of the graph audited
    watcher_id  — "WATCHER_A" or "WATCHER_B"
    findings    — list of Finding objects
    passed      — True if no FAIL or ERROR findings
    severity    — worst severity observed (drives Council recommendation)
    """
    graph_hash: str
    watcher_id: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(f.level in (FindingLevel.OK, FindingLevel.WARN)
                   for f in self.findings)

    @property
    def has_errors(self) -> bool:
        return any(f.level == FindingLevel.ERROR for f in self.findings)

    @property
    def has_failures(self) -> bool:
        return any(f.level == FindingLevel.FAIL for f in self.findings)

    @property
    def severity(self) -> Severity:
        if self.has_errors or self.has_failures:
            return Severity.ERROR
        if any(f.level == FindingLevel.WARN for f in self.findings):
            return Severity.WARNING
        return Severity.INFO

    def summary(self) -> str:
        ok   = sum(1 for f in self.findings if f.level == FindingLevel.OK)
        warn = sum(1 for f in self.findings if f.level == FindingLevel.WARN)
        fail = sum(1 for f in self.findings if f.level == FindingLevel.FAIL)
        err  = sum(1 for f in self.findings if f.level == FindingLevel.ERROR)
        return (f"{self.watcher_id} graph={self.graph_hash[:12]}… "
                f"OK={ok} WARN={warn} FAIL={fail} ERR={err} "
                f"passed={self.passed}")


# ─── WATCHER-A ────────────────────────────────────────────────────────────────

class WatcherA:
    """
    Internal consistency auditor.

    Checks structural and temporal consistency of a CGIRGraph.
    Does not check adversarial properties — that is Watcher-B's role.
    """

    WATCHER_ID = "WATCHER_A"

    # Required invariants that every edge should carry
    REQUIRED_INVARIANTS = ["I1"]

    def audit(self, graph: CGIRGraph) -> WatcherReport:
        """
        Audit the graph. Returns a WatcherReport.
        Never raises — internal errors become ERROR findings.
        """
        try:
            graph_hash = stable_hash(graph)
        except Exception as exc:
            return WatcherReport(
                graph_hash="",
                watcher_id=self.WATCHER_ID,
                findings=[Finding(
                    check="HASH",
                    level=FindingLevel.ERROR,
                    detail=f"Failed to hash graph: {exc}",
                )],
            )

        findings: List[Finding] = []

        try:
            findings.extend(self._check_temporal_consistency(graph))
            findings.extend(self._check_signal_binding_coherence(graph))
            findings.extend(self._check_invariant_mask_completeness(graph))
            findings.extend(self._check_root_tip_path(graph))
            findings.extend(self._check_confidence_plausibility(graph))
        except Exception as exc:
            findings.append(Finding(
                check="AUDIT_INTERNAL",
                level=FindingLevel.ERROR,
                detail=f"Watcher-A internal error: {exc}",
            ))

        return WatcherReport(
            graph_hash=graph_hash,
            watcher_id=self.WATCHER_ID,
            findings=findings,
        )

    # ── Check 1: Temporal consistency ─────────────────────────────────────────

    def _check_temporal_consistency(self, graph: CGIRGraph) -> List[Finding]:
        """
        Edges should flow forward in time or stay flat.
        An edge from a high-time node to a low-time node is suspicious.
        """
        findings = []
        for edge in graph.edges():
            from_node = graph.get_node(edge.from_id)
            to_node   = graph.get_node(edge.to_id)
            if from_node is None or to_node is None:
                continue  # validator handles missing nodes
            if to_node.logical_time < from_node.logical_time:
                findings.append(Finding(
                    check="TEMPORAL_CONSISTENCY",
                    level=FindingLevel.WARN,
                    detail=(
                        f"Edge '{edge.id}' goes backward in time: "
                        f"from {from_node.id}@t={from_node.logical_time} "
                        f"to {to_node.id}@t={to_node.logical_time}"
                    ),
                    edge_id=edge.id,
                ))

        if not findings:
            findings.append(Finding(
                check="TEMPORAL_CONSISTENCY",
                level=FindingLevel.OK,
                detail="All edges flow forward or flat in logical time",
            ))
        return findings

    # ── Check 2: Signal binding coherence ─────────────────────────────────────

    def _check_signal_binding_coherence(self, graph: CGIRGraph) -> List[Finding]:
        """
        If an edge has a signal_binding, the signal's valid_for range
        should contain the edge's logical time window.
        """
        findings = []
        for edge in graph.edges():
            if edge.signal_binding is None:
                continue
            sig = graph.get_signal(edge.signal_binding)
            if sig is None:
                continue  # validator handles missing signals
            if sig.valid_for is None:
                continue  # no time constraint on signal

            from_node = graph.get_node(edge.from_id)
            to_node   = graph.get_node(edge.to_id)
            if from_node is None or to_node is None:
                continue

            edge_start = from_node.logical_time
            edge_end   = to_node.logical_time

            if not sig.valid_for.contains(edge_start):
                findings.append(Finding(
                    check="SIGNAL_BINDING_COHERENCE",
                    level=FindingLevel.WARN,
                    detail=(
                        f"Signal '{sig.id}' valid_for "
                        f"[{sig.valid_for.start_time},{sig.valid_for.end_time}] "
                        f"does not contain edge start t={edge_start}"
                    ),
                    edge_id=edge.id,
                ))

        if not any(f.check == "SIGNAL_BINDING_COHERENCE" for f in findings):
            findings.append(Finding(
                check="SIGNAL_BINDING_COHERENCE",
                level=FindingLevel.OK,
                detail="All signal bindings are temporally coherent",
            ))
        return findings

    # ── Check 3: Invariant mask completeness ──────────────────────────────────

    def _check_invariant_mask_completeness(self, graph: CGIRGraph) -> List[Finding]:
        """
        Every edge should declare at least I1 in its invariant_mask.
        I1 (Execution Closure) is always required.
        """
        findings = []
        for edge in graph.edges():
            for req in self.REQUIRED_INVARIANTS:
                if req not in edge.invariant_mask:
                    findings.append(Finding(
                        check="INVARIANT_MASK_COMPLETENESS",
                        level=FindingLevel.WARN,
                        detail=(
                            f"Edge '{edge.id}' missing required "
                            f"invariant '{req}' in mask"
                        ),
                        edge_id=edge.id,
                    ))

        if not any(f.check == "INVARIANT_MASK_COMPLETENESS" for f in findings):
            findings.append(Finding(
                check="INVARIANT_MASK_COMPLETENESS",
                level=FindingLevel.OK,
                detail="All edges carry required invariant declarations",
            ))
        return findings

    # ── Check 4: Root-to-tip path exists ──────────────────────────────────────

    def _check_root_tip_path(self, graph: CGIRGraph) -> List[Finding]:
        """
        If root and tip are set, there should be a path from root to tip.
        Uses simple BFS — does not enforce shortest path.
        """
        if graph.root is None or graph.tip is None:
            return [Finding(
                check="ROOT_TIP_PATH",
                level=FindingLevel.WARN,
                detail="root or tip not set — cannot verify path",
            )]

        if graph.root == graph.tip:
            return [Finding(
                check="ROOT_TIP_PATH",
                level=FindingLevel.OK,
                detail="root == tip (single-node or trivial graph)",
            )]

        # BFS from root
        visited = set()
        queue = [graph.root]
        while queue:
            current = queue.pop(0)
            if current == graph.tip:
                return [Finding(
                    check="ROOT_TIP_PATH",
                    level=FindingLevel.OK,
                    detail=f"Path exists from root '{graph.root}' to tip '{graph.tip}'",
                )]
            if current in visited:
                continue
            visited.add(current)
            for edge in graph.outgoing_edges(current):
                queue.append(edge.to_id)

        return [Finding(
            check="ROOT_TIP_PATH",
            level=FindingLevel.FAIL,
            detail=(
                f"No path from root '{graph.root}' to tip '{graph.tip}' "
                f"(visited {len(visited)} nodes)"
            ),
        )]

    # ── Check 5: Confidence plausibility ──────────────────────────────────────

    def _check_confidence_plausibility(self, graph: CGIRGraph) -> List[Finding]:
        """
        Multiple signals on the same graph should have consistent confidence.
        If one signal has confidence 0.99 and another has 0.01, that is
        suspicious but not necessarily wrong — flagged as WARN.
        """
        findings = []
        sigs = graph.signals()
        if len(sigs) < 2:
            findings.append(Finding(
                check="CONFIDENCE_PLAUSIBILITY",
                level=FindingLevel.OK,
                detail="Fewer than 2 signals — plausibility check skipped",
            ))
            return findings

        confs = [s.confidence for s in sigs]
        conf_range = max(confs) - min(confs)
        if conf_range > 0.80:
            findings.append(Finding(
                check="CONFIDENCE_PLAUSIBILITY",
                level=FindingLevel.WARN,
                detail=(
                    f"Wide confidence spread across signals: "
                    f"range={conf_range:.3f} (max={max(confs):.3f}, "
                    f"min={min(confs):.3f})"
                ),
            ))
        else:
            findings.append(Finding(
                check="CONFIDENCE_PLAUSIBILITY",
                level=FindingLevel.OK,
                detail=f"Signal confidence spread is acceptable (range={conf_range:.3f})",
            ))
        return findings


# ─── MODULE-LEVEL CONVENIENCE ─────────────────────────────────────────────────

def audit(graph: CGIRGraph) -> WatcherReport:
    """Convenience: WatcherA().audit(graph)."""
    return WatcherA().audit(graph)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _make_clean_graph():
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="STEP", invariant_mask=["I1"]))
    g.set_root("n0"); g.set_tip("n1")
    return g


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_clean_graph_passes() -> bool:
    g = _make_clean_graph()
    r = audit(g)
    assert r.passed, f"Expected pass: {[f.detail for f in r.findings if f.level != FindingLevel.OK]}"
    assert r.watcher_id == "WATCHER_A"
    return True

def _test_report_has_graph_hash() -> bool:
    g = _make_clean_graph()
    r = audit(g)
    assert len(r.graph_hash) == 64
    return True

def _test_backward_time_edge_warns() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=5))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=2))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="BACK", invariant_mask=["I1"]))
    g.set_root("n0"); g.set_tip("n1")
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "TEMPORAL_CONSISTENCY" in warn_checks
    return True

def _test_missing_i1_warns() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="STEP", invariant_mask=[]))
    g.set_root("n0"); g.set_tip("n1")
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "INVARIANT_MASK_COMPLETENESS" in warn_checks
    return True

def _test_no_path_root_to_tip_fails() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="n2", node_type=NodeType.STATE, logical_time=2))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="STEP", invariant_mask=["I1"]))
    g.set_root("n0"); g.set_tip("n2")  # n2 unreachable
    r = audit(g)
    fail_checks = [f.check for f in r.findings if f.level == FindingLevel.FAIL]
    assert "ROOT_TIP_PATH" in fail_checks
    return True

def _test_valid_path_passes() -> bool:
    g = _make_clean_graph()
    r = audit(g)
    ok_checks = [f.check for f in r.findings if f.level == FindingLevel.OK]
    assert "ROOT_TIP_PATH" in ok_checks
    return True

def _test_severity_info_on_clean_graph() -> bool:
    r = audit(_make_clean_graph())
    assert r.severity == Severity.INFO
    return True

def _test_severity_warning_on_issues() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="STEP", invariant_mask=[]))  # missing I1
    g.set_root("n0"); g.set_tip("n1")
    r = audit(g)
    assert r.severity == Severity.WARNING
    return True

def _test_summary_string() -> bool:
    r = audit(_make_clean_graph())
    s = r.summary()
    assert "WATCHER_A" in s
    assert "passed=True" in s
    return True

def _test_deterministic() -> bool:
    g = _make_clean_graph()
    r1 = audit(g)
    r2 = audit(g)
    assert r1.graph_hash == r2.graph_hash
    assert r1.passed == r2.passed
    assert len(r1.findings) == len(r2.findings)
    return True

def _test_wide_confidence_warns() -> bool:
    from cgir_types import Edge, Node, NodeType, Severity as Sev, SignalNode
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="STEP", invariant_mask=["I1"]))
    g.set_root("n0"); g.set_tip("n1")
    g.add_signal(SignalNode(id="s0", node_type=NodeType.SIGNAL,
                            logical_time=0, confidence=0.99, emitted_by="COUNCIL"))
    g.add_signal(SignalNode(id="s1", node_type=NodeType.SIGNAL,
                            logical_time=0, confidence=0.01, emitted_by="COUNCIL"))
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "CONFIDENCE_PLAUSIBILITY" in warn_checks
    return True

def _test_passed_false_when_fail() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_node(Node(id="tip", node_type=NodeType.STATE, logical_time=2))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1",
                    event_type="STEP", invariant_mask=["I1"]))
    g.set_root("n0"); g.set_tip("tip")
    r = audit(g)
    assert not r.passed
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
    print("WATCHER-A — Labyrinth-OS")
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
    print(f"\n{'=' * 70}\n  WATCHER-A — COMPLETE\n{'=' * 70}")
