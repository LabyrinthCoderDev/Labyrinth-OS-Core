"""
cgir_gate.py — Labyrinth-OS / CGIR Phase 1
==========================================
Causal Graph Intermediate Representation — Minimal Gate

Pure deterministic function.

Input:  validated CGIRGraph
Output: GateResult(ALLOW) or GateResult(BLOCK)

Rules (from INVARIANTS.md and spec/GATE.md):
  - If any signal has severity == CRITICAL → BLOCK
  - Otherwise → ALLOW

STRICT REQUIREMENTS:
  - No internal state. No class-level variables.
  - No side effects. No I/O. No logging inside evaluate().
  - Same input → same output. Always.
  - Gate does NOT validate the graph — caller must run cgir_validator first.
  - Gate does NOT accept unvalidated graphs without raising.

The Gate is the ONLY decision authority.
Nothing executes without Gate approval.
Nothing bypasses Gate.

References:
  ARCHITECTURE.md  — Layer L11 (Gate)
  INVARIANTS.md    — I2 Gate Determinism, I10 Fail Closed
  spec/GATE.md     — Decision priority, GateDecision values
"""

from __future__ import annotations

import hashlib
from typing import Optional

from cgir_types import GateDecision, GateResult, Severity, ValidationResult
from cgir_core import CGIRGraph
from cgir_validator import validate as _validate


# ─── GATE FUNCTION ────────────────────────────────────────────────────────────

def evaluate(graph: CGIRGraph) -> GateResult:
    """
    Pure gate evaluation. No state. No side effects. Same graph → same result.

    Gate Precedence (Invariant I5):
      CGIR Gate is the FORMAL layer (structural validity).
      GuardianSlot is the OPERATIONAL layer (safety margin + sensor bounds).
      Both must agree for execution. Neither alone is sufficient.

      CGIR BLOCK  → GuardianSlot MUST NOT execute (mandatory override).
      CGIR ALLOW  → GuardianSlot MAY execute (necessary, not sufficient).

    Decision logic:
      Priority 1: Any CRITICAL signal → BLOCK (unconditional, GuardianSlot override denied)
      Priority 2: Any ERROR signal    → BLOCK (structural violation, same)
      Priority 3: WARNING/INFO only   → ALLOW (GuardianSlot decides on operational margin)
      Priority 4: No signals          → ALLOW (GuardianSlot decides on operational margin)

    WARNING does not BLOCK at CGIR level. GuardianSlot receives full sensor
    readings and can BLOCK on confidence / τ / χ margin. This preserves the
    formal/operational separation (Invariant I7).

    Precondition: graph validated by cgir_validator before calling this.
    """
    critical = [s for s in graph.signals() if s.severity == Severity.CRITICAL]
    errors   = [s for s in graph.signals() if s.severity == Severity.ERROR]

    if critical:
        ids = ", ".join(f"'{s.id}'" for s in critical[:3])
        return GateResult(
            decision=GateDecision.BLOCK,
            reason=(
                f"CRITICAL signal(s) present: {ids}. "
                f"Blocked unconditionally (I2, I5). "
                f"GuardianSlot override not permitted."
            ),
        )

    if errors:
        ids = ", ".join(f"'{s.id}'" for s in errors[:3])
        return GateResult(
            decision=GateDecision.BLOCK,
            reason=(
                f"ERROR signal(s) present: {ids}. "
                f"Structural violation — graph invalid for execution (I5). "
                f"GuardianSlot override not permitted."
            ),
        )

    return GateResult(
        decision=GateDecision.ALLOW,
        reason=(
            "No CRITICAL or ERROR signals. "
            "GuardianSlot evaluates operational margin (I5)."
        ),
    )


def evaluate_with_validation(graph: CGIRGraph) -> tuple[ValidationResult, Optional[GateResult]]:
    """
    Validate then evaluate. Returns (validation_result, gate_result).
    gate_result is None if validation failed — an invalid graph never reaches Gate.

    This is the safe entry point for callers who have not pre-validated.
    """
    result = _validate(graph)
    if not result.valid:
        return result, None
    return result, evaluate(graph)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _build_clean_graph() -> CGIRGraph:
    """Two nodes, one edge, no signals. Valid, should ALLOW."""
    from cgir_types import Edge, Node, NodeType
    g = CGIRGraph()
    g.add_node(Node(id="n0", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="n1", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="e0", from_id="n0", to_id="n1", event_type="STEP"))
    return g


def _add_signal(graph: CGIRGraph, severity: Severity,
                signal_id: str = "sig0") -> CGIRGraph:
    """Add a signal of given severity to graph. Does NOT bind to an edge."""
    from cgir_types import NodeType, SignalNode
    sig = SignalNode(
        id=signal_id, node_type=NodeType.SIGNAL, logical_time=0,
        severity=severity, confidence=0.8,
        category="TEST", source="VECTOR", emitted_by="COUNCIL",
    )
    graph.add_signal(sig)
    return graph


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_clean_graph_allows() -> bool:
    """Graph with no signals → ALLOW. GuardianSlot decides margin."""
    g = _build_clean_graph()
    result = evaluate(g)
    assert result.decision == GateDecision.ALLOW
    assert "GuardianSlot" in result.reason
    return True


def _test_info_signal_allows() -> bool:
    """Graph with only INFO signal → ALLOW."""
    g = _add_signal(_build_clean_graph(), Severity.INFO)
    result = evaluate(g)
    assert result.decision == GateDecision.ALLOW
    return True


def _test_warning_signal_allows() -> bool:
    """Graph with only WARNING signal → ALLOW."""
    g = _add_signal(_build_clean_graph(), Severity.WARNING)
    result = evaluate(g)
    assert result.decision == GateDecision.ALLOW
    return True


def _test_error_signal_blocks_at_gate() -> bool:
    """ERROR signal → BLOCK at CGIR level (structural violation per I5)."""
    g = _add_signal(_build_clean_graph(), Severity.ERROR)
    result = evaluate(g)
    assert result.decision == GateDecision.BLOCK
    return True


def _test_critical_signal_blocks() -> bool:
    """Graph with any CRITICAL signal → BLOCK."""
    g = _add_signal(_build_clean_graph(), Severity.CRITICAL)
    result = evaluate(g)
    assert result.decision == GateDecision.BLOCK
    assert "CRITICAL" in result.reason
    assert "sig0" in result.reason
    return True


def _test_critical_among_many_blocks() -> bool:
    """CRITICAL among multiple signals still causes BLOCK."""
    g = _build_clean_graph()
    _add_signal(g, Severity.INFO,     "s_info")
    _add_signal(g, Severity.WARNING,  "s_warn")
    _add_signal(g, Severity.CRITICAL, "s_crit")
    _add_signal(g, Severity.ERROR,    "s_err")
    result = evaluate(g)
    assert result.decision == GateDecision.BLOCK
    return True


def _test_same_input_same_output() -> bool:
    """Calling evaluate twice on same graph returns identical results."""
    g = _build_clean_graph()
    r1 = evaluate(g)
    r2 = evaluate(g)
    assert r1.decision == r2.decision
    assert r1.reason == r2.reason
    return True


def _test_same_input_same_output_block() -> bool:
    """BLOCK result is deterministic across calls."""
    g = _add_signal(_build_clean_graph(), Severity.CRITICAL)
    r1 = evaluate(g)
    r2 = evaluate(g)
    assert r1.decision == r2.decision
    assert r1.reason == r2.reason
    return True


def _test_gate_result_is_gateresult() -> bool:
    """evaluate() returns a GateResult instance."""
    g = _build_clean_graph()
    result = evaluate(g)
    assert isinstance(result, GateResult)
    return True


def _test_gate_result_decision_is_enum() -> bool:
    """decision field is a GateDecision enum member."""
    g = _build_clean_graph()
    result = evaluate(g)
    assert isinstance(result.decision, GateDecision)
    return True


def _test_block_result_has_reason() -> bool:
    """BLOCK result always has a non-empty reason string."""
    g = _add_signal(_build_clean_graph(), Severity.CRITICAL)
    result = evaluate(g)
    assert result.decision == GateDecision.BLOCK
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0
    return True


def _test_allow_result_has_guardianslot_in_reason() -> bool:
    """ALLOW reason cites GuardianSlot — I5 visible in audit trail."""
    g = _build_clean_graph()
    result = evaluate(g)
    assert result.decision == GateDecision.ALLOW
    assert "GuardianSlot" in result.reason
    return True


def _test_gate_result_serializes() -> bool:
    """GateResult.to_dict() works correctly."""
    g = _add_signal(_build_clean_graph(), Severity.CRITICAL)
    result = evaluate(g)
    d = result.to_dict()
    assert d["decision"] == "BLOCK"
    assert len(d["reason"]) > 0
    return True


def _test_evaluate_with_validation_valid_graph() -> bool:
    """evaluate_with_validation on valid graph returns (valid, gate_result)."""
    g = _build_clean_graph()
    vr, gr = evaluate_with_validation(g)
    assert vr.valid is True
    assert gr is not None
    assert isinstance(gr, GateResult)
    return True


def _test_evaluate_with_validation_invalid_graph() -> bool:
    """evaluate_with_validation on invalid graph returns (invalid, None)."""
    g = CGIRGraph()  # empty, invalid
    vr, gr = evaluate_with_validation(g)
    assert vr.valid is False
    assert gr is None
    return True


def _test_evaluate_with_validation_critical_blocks() -> bool:
    """evaluate_with_validation with CRITICAL signal returns BLOCK."""
    g = _add_signal(_build_clean_graph(), Severity.CRITICAL)
    vr, gr = evaluate_with_validation(g)
    assert vr.valid is True
    assert gr is not None
    assert gr.decision == GateDecision.BLOCK
    return True


def _test_multiple_critical_signals_block_on_first() -> bool:
    """With multiple CRITICAL signals, gate blocks (reason mentions first found)."""
    g = _build_clean_graph()
    _add_signal(g, Severity.CRITICAL, "first_critical")
    _add_signal(g, Severity.CRITICAL, "second_critical")
    result = evaluate(g)
    assert result.decision == GateDecision.BLOCK
    # Reason mentions a critical signal id — does not need to name both
    assert "first_critical" in result.reason or "second_critical" in result.reason
    return True


def _test_empty_signals_list_allows() -> bool:
    """Graph with zero signals ALLOWS."""
    g = _build_clean_graph()
    assert len(g.signals()) == 0
    result = evaluate(g)
    assert result.decision == GateDecision.ALLOW
    return True


# ─── TEST RUNNER ──────────────────────────────────────────────────────────────


def _test_error_signal_blocks() -> bool:
    """ERROR signal → BLOCK (Invariant I5: ERROR is structural violation)."""
    g = _add_signal(_build_clean_graph(), Severity.ERROR, 'sig_err')
    result = evaluate(g)
    assert result.decision == GateDecision.BLOCK, f'Expected BLOCK, got {result.decision}'
    assert 'ERROR' in result.reason
    return True

def _test_warning_signal_allows() -> bool:
    """WARNING signal → ALLOW at CGIR level (GuardianSlot decides operational margin)."""
    g = _add_signal(_build_clean_graph(), Severity.WARNING, 'sig_warn')
    result = evaluate(g)
    assert result.decision == GateDecision.ALLOW, f'Expected ALLOW, got {result.decision}'
    return True

def _test_allow_reason_mentions_guardianslot() -> bool:
    """ALLOW reason references GuardianSlot — makes I5 visible in the audit trail."""
    g = _build_clean_graph()
    result = evaluate(g)
    assert 'GuardianSlot' in result.reason
    return True

def _test_block_reason_denies_guardianslot_override() -> bool:
    """BLOCK reason states GuardianSlot override not permitted (I5 explicit)."""
    g = _add_signal(_build_clean_graph(), Severity.CRITICAL, 'sig_crit')
    result = evaluate(g)
    assert 'override not permitted' in result.reason
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


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("CGIR GATE — Labyrinth-OS Phase 1")
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
    print(f"  File:    cgir_gate.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Phase 1 Step 5: cgir_gate.py — COMPLETE")
    print(f"{'=' * 70}")
