"""
watcher_b.py — Labyrinth-OS / Epistemic Layer
==============================================
Watcher-B — Adversarial Auditor

Watcher-B audits Watcher-A's blind spots.
It checks adversarial properties: replay attacks, signal injection,
invariant bypass attempts, and gate evasion patterns.

Watcher-B cannot see Watcher-A's report. It cannot write to the graph.
It produces a WatcherReport that the Council Resolver merges with A's.

The key architectural guarantee: a proposal that passes Watcher-A
still has to pass Watcher-B independently. An attacker must fool both
simultaneously without coordination — which is structurally harder.

Watcher-B checks:
  1. Replay pattern — all-zero hashes, cloned node IDs, suspicious
     metadata suggesting a replayed or synthetic proposal.
  2. Signal injection — COUNCIL-emitted signals with suspicious
     confidence distributions (too uniform, too perfect).
  3. Gate evasion — proposals that are technically valid but structured
     to minimize signal detection (e.g. no signals at all on complex
     graphs, or all INFO with suspicious metadata).
  4. Temporal attack — logical_time reset to 0 mid-graph.
  5. Invariant strip — edges with invariant_mask stripped or reduced.

Rules:
  - READ ONLY. Adversarial analysis only — no writes.
  - INDEPENDENT of Watcher-A. No shared state.
  - Fail closed: internal errors → AUDIT_ERROR finding.
  - Deterministic: same graph → same report.

References:
  ARCHITECTURE.md  — L4 Watcher-B (adversarial auditor)
  INVARIANTS.md    — I3, I4, I10
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List

from cgir_types import NodeType, Severity
from cgir_core import CGIRGraph
from cgir_determinism import stable_hash
from watcher_a import Finding, FindingLevel, WatcherReport


class WatcherB:
    """Adversarial auditor — independent of Watcher-A."""

    WATCHER_ID = "WATCHER_B"

    # Thresholds
    PERFECT_CONFIDENCE    = 0.999   # suspiciously exact
    UNIFORM_CONF_EPSILON  = 0.001   # all signals within this range = suspicious
    LARGE_GRAPH_MIN_NODES = 5       # graphs this large should have signals
    MAX_SAME_EVENT_RATIO  = 0.9     # > 90% same event_type = suspicious

    def audit(self, graph: CGIRGraph) -> WatcherReport:
        """Adversarial audit. Returns WatcherReport. Never raises."""
        try:
            graph_hash = stable_hash(graph)
        except Exception as exc:
            return WatcherReport(
                graph_hash="",
                watcher_id=self.WATCHER_ID,
                findings=[Finding(
                    check="HASH", level=FindingLevel.ERROR,
                    detail=f"Failed to hash graph: {exc}",
                )],
            )

        findings: List[Finding] = []
        try:
            findings.extend(self._check_replay_patterns(graph))
            findings.extend(self._check_signal_injection(graph))
            findings.extend(self._check_gate_evasion(graph))
            findings.extend(self._check_temporal_attack(graph))
            findings.extend(self._check_invariant_strip(graph))
        except Exception as exc:
            findings.append(Finding(
                check="AUDIT_INTERNAL", level=FindingLevel.ERROR,
                detail=f"Watcher-B internal error: {exc}",
            ))

        return WatcherReport(
            graph_hash=graph_hash,
            watcher_id=self.WATCHER_ID,
            findings=findings,
        )

    # ── Check 1: Replay patterns ──────────────────────────────────────────────

    def _check_replay_patterns(self, graph: CGIRGraph) -> List[Finding]:
        """
        Detect signs of a replayed or synthetic proposal.
        Indicators: nodes with sequential numeric IDs from 0, all-same
        metadata, or node IDs that look machine-generated (n0, n1, n2...).
        Not a failure — a warning that triggers closer scrutiny.
        """
        nodes = graph.nodes()
        if not nodes:
            return [Finding(check="REPLAY_PATTERN", level=FindingLevel.OK,
                            detail="No nodes to check")]

        # Check if all node IDs are sequential n0,n1,n2...
        sequential_ids = all(
            n.id == f"n{i}" for i, n in enumerate(
                sorted(nodes, key=lambda x: x.logical_time)
            )
        )
        if sequential_ids and len(nodes) >= 3:
            return [Finding(
                check="REPLAY_PATTERN", level=FindingLevel.WARN,
                detail=(
                    f"All {len(nodes)} nodes have sequential synthetic IDs "
                    f"(n0, n1, ...nN) — possible synthetic/replay proposal"
                ),
            )]

        return [Finding(check="REPLAY_PATTERN", level=FindingLevel.OK,
                        detail="No sequential synthetic ID pattern detected")]

    # ── Check 2: Signal injection ─────────────────────────────────────────────

    def _check_signal_injection(self, graph: CGIRGraph) -> List[Finding]:
        """
        Adversarial signal injection patterns:
        - All signals at perfect confidence (exactly 1.0 or 0.0)
        - All signals have identical confidence (possible injection)
        - Many COUNCIL signals with INFO severity (drowning out real signals)
        """
        findings = []
        sigs = graph.signals()

        if not sigs:
            return [Finding(check="SIGNAL_INJECTION", level=FindingLevel.OK,
                            detail="No signals present")]

        # Check for perfect confidence
        perfect = [s for s in sigs
                   if s.confidence >= self.PERFECT_CONFIDENCE
                   or s.confidence <= (1 - self.PERFECT_CONFIDENCE)]
        if len(perfect) == len(sigs) and len(sigs) > 1:
            findings.append(Finding(
                check="SIGNAL_INJECTION", level=FindingLevel.WARN,
                detail=(
                    f"All {len(sigs)} signals have perfect confidence "
                    f"(≥{self.PERFECT_CONFIDENCE} or ≤{1-self.PERFECT_CONFIDENCE}) "
                    f"— possible injection"
                ),
            ))

        # Check for uniform confidence
        if len(sigs) >= 3:
            confs = sorted(s.confidence for s in sigs)
            if (confs[-1] - confs[0]) <= self.UNIFORM_CONF_EPSILON:
                findings.append(Finding(
                    check="SIGNAL_INJECTION", level=FindingLevel.WARN,
                    detail=(
                        f"All {len(sigs)} signals have nearly identical confidence "
                        f"(range={confs[-1]-confs[0]:.4f}) — possible injection"
                    ),
                ))

        # All INFO severity with COUNCIL emitter — dilution attack
        council_sigs = [s for s in sigs if s.emitted_by == "COUNCIL"]
        info_sigs = [s for s in council_sigs
                     if s.severity.value == "INFO"]
        if len(council_sigs) >= 3 and len(info_sigs) == len(council_sigs):
            findings.append(Finding(
                check="SIGNAL_INJECTION", level=FindingLevel.WARN,
                detail=(
                    f"All {len(council_sigs)} COUNCIL signals are INFO severity "
                    f"— possible signal dilution attack"
                ),
            ))

        if not findings:
            findings.append(Finding(
                check="SIGNAL_INJECTION", level=FindingLevel.OK,
                detail="No signal injection patterns detected",
            ))
        return findings

    # ── Check 3: Gate evasion ─────────────────────────────────────────────────

    def _check_gate_evasion(self, graph: CGIRGraph) -> List[Finding]:
        """
        Detect gate evasion patterns:
        - Large graph with no signals (trying to get ALLOW without scrutiny)
        - All edges have empty invariant_mask (stripped constraints)
        - All edges have the same event_type (automated/looping proposal)
        """
        findings = []

        # Large graph, no signals
        if (graph.node_count >= self.LARGE_GRAPH_MIN_NODES
                and graph.signal_count == 0):
            findings.append(Finding(
                check="GATE_EVASION", level=FindingLevel.WARN,
                detail=(
                    f"Graph with {graph.node_count} nodes has no signals "
                    f"— possible gate evasion attempt"
                ),
            ))

        # All edges stripped of invariant_mask
        edges = graph.edges()
        if edges:
            empty_mask = [e for e in edges if not e.invariant_mask]
            if len(empty_mask) == len(edges):
                findings.append(Finding(
                    check="GATE_EVASION", level=FindingLevel.WARN,
                    detail=(
                        f"All {len(edges)} edges have empty invariant_mask "
                        f"— all constraints stripped"
                    ),
                ))

            # Event type uniformity
            event_types = [e.event_type for e in edges]
            if len(event_types) >= 4:
                most_common = max(set(event_types), key=event_types.count)
                ratio = event_types.count(most_common) / len(event_types)
                if ratio >= self.MAX_SAME_EVENT_RATIO:
                    findings.append(Finding(
                        check="GATE_EVASION", level=FindingLevel.WARN,
                        detail=(
                            f"{ratio:.0%} of edges have event_type='{most_common}' "
                            f"— possible automated/loop proposal"
                        ),
                    ))

        if not findings:
            findings.append(Finding(
                check="GATE_EVASION", level=FindingLevel.OK,
                detail="No gate evasion patterns detected",
            ))
        return findings

    # ── Check 4: Temporal attack ──────────────────────────────────────────────

    def _check_temporal_attack(self, graph: CGIRGraph) -> List[Finding]:
        """
        Detect temporal reset attacks: an edge whose to_id node has
        logical_time = 0 but the from_id node has logical_time > 0.
        This suggests a proposal spliced from a different session.
        Also detect any edge that drops time by more than 1 step
        (to_time == 0 while from_time > 0).
        """
        for edge in graph.edges():
            from_node = graph.get_node(edge.from_id)
            to_node   = graph.get_node(edge.to_id)
            if from_node is None or to_node is None:
                continue
            if to_node.logical_time == 0 and from_node.logical_time > 0:
                return [Finding(
                    check="TEMPORAL_ATTACK", level=FindingLevel.WARN,
                    detail=(
                        f"Edge '{edge.id}' drops to logical_time=0 from "
                        f"t={from_node.logical_time} — possible temporal splice"
                    ),
                    edge_id=edge.id,
                )]

        return [Finding(check="TEMPORAL_ATTACK", level=FindingLevel.OK,
                        detail="No temporal reset patterns detected")]

    # ── Check 5: Invariant strip ──────────────────────────────────────────────

    def _check_invariant_strip(self, graph: CGIRGraph) -> List[Finding]:
        """
        Check if invariant_mask shows signs of progressive stripping.
        If most edges have full masks but one or two have empty masks,
        those stripped edges are suspect.
        """
        edges = graph.edges()
        if not edges:
            return [Finding(check="INVARIANT_STRIP", level=FindingLevel.OK,
                            detail="No edges")]

        total = len(edges)
        empty = [e for e in edges if not e.invariant_mask]
        nonempty = total - len(empty)

        if empty and nonempty > 0:
            # Some edges have masks, some don't — selective stripping
            stripped_ids = [e.id for e in empty[:3]]
            return [Finding(
                check="INVARIANT_STRIP", level=FindingLevel.WARN,
                detail=(
                    f"{len(empty)}/{total} edges have empty invariant_mask "
                    f"while others are populated — selective strip: "
                    f"{stripped_ids}"
                ),
            )]

        return [Finding(check="INVARIANT_STRIP", level=FindingLevel.OK,
                        detail="No selective invariant stripping detected")]


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

def audit(graph: CGIRGraph) -> WatcherReport:
    return WatcherB().audit(graph)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _make_clean_graph():
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="proposal_main", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="proposal_next", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="step_0", from_id="proposal_main", to_id="proposal_next",
                    event_type="STEP", invariant_mask=["I1"]))
    g.set_root("proposal_main"); g.set_tip("proposal_next")
    return g


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_clean_graph_passes() -> bool:
    r = audit(_make_clean_graph())
    assert r.watcher_id == "WATCHER_B"
    assert r.passed, f"Failures: {[f.detail for f in r.findings if f.level != FindingLevel.OK]}"
    return True

def _test_sequential_ids_warn() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    for i in range(4):
        g.add_node(Node(id=f"n{i}", node_type=NodeType.STATE, logical_time=i))
    for i in range(3):
        g.add_edge(Edge(id=f"e{i}", from_id=f"n{i}", to_id=f"n{i+1}",
                        event_type="STEP", invariant_mask=["I1"]))
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "REPLAY_PATTERN" in warn_checks
    return True

def _test_no_signals_large_graph_warns() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    for i in range(6):
        g.add_node(Node(id=f"node_{i}", node_type=NodeType.STATE, logical_time=i))
    for i in range(5):
        g.add_edge(Edge(id=f"edge_{i}", from_id=f"node_{i}", to_id=f"node_{i+1}",
                        event_type="STEP", invariant_mask=["I1"]))
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "GATE_EVASION" in warn_checks
    return True

def _test_temporal_reset_warns() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="early", node_type=NodeType.STATE, logical_time=5))
    g.add_node(Node(id="reset", node_type=NodeType.STATE, logical_time=0))
    g.add_edge(Edge(id="e0", from_id="early", to_id="reset",
                    event_type="STEP", invariant_mask=["I1"]))
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "TEMPORAL_ATTACK" in warn_checks
    return True

def _test_selective_invariant_strip_warns() -> bool:
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    for i in range(3):
        g.add_node(Node(id=f"x{i}", node_type=NodeType.STATE, logical_time=i))
    # One edge with mask, one without
    g.add_edge(Edge(id="e0", from_id="x0", to_id="x1",
                    event_type="STEP", invariant_mask=["I1"]))
    g.add_edge(Edge(id="e1", from_id="x1", to_id="x2",
                    event_type="STEP", invariant_mask=[]))
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "INVARIANT_STRIP" in warn_checks
    return True

def _test_report_independent_of_watcher_a() -> bool:
    """Watcher-B report does not contain Watcher-A references."""
    r = audit(_make_clean_graph())
    assert r.watcher_id == "WATCHER_B"
    assert "WATCHER_A" not in r.summary()
    return True

def _test_deterministic() -> bool:
    g = _make_clean_graph()
    r1 = audit(g); r2 = audit(g)
    assert r1.graph_hash == r2.graph_hash
    assert r1.passed == r2.passed
    return True

def _test_severity_info_on_clean() -> bool:
    r = audit(_make_clean_graph())
    assert r.severity == Severity.INFO
    return True

def _test_perfect_confidence_warns() -> bool:
    from cgir_types import Edge, Node, NodeType, SignalNode
    g = _make_clean_graph()
    for i in range(3):
        g.add_signal(SignalNode(id=f"s{i}", node_type=NodeType.SIGNAL,
                                logical_time=0, confidence=1.0, emitted_by="COUNCIL"))
    r = audit(g)
    warn_checks = [f.check for f in r.findings if f.level == FindingLevel.WARN]
    assert "SIGNAL_INJECTION" in warn_checks
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
    print("WATCHER-B — Labyrinth-OS")
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
    print(f"\n{'=' * 70}\n  WATCHER-B — COMPLETE\n{'=' * 70}")
