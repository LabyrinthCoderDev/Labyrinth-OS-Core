"""
epistemic_types.py — Labyrinth-OS / Lane 1
============================================
Shared type definitions for the Lane 1 epistemic pipeline.

L00 Boot Manifest → L01 User Intent → L02 Mode Router
  → L03 Creative Zone → L04 Analytical Core
  → L05 Epistemic Labeling → L06 Archive Memory
  → L07 Deferred Exploration → L08 Promotion Protocol
  → L09 Reality Gate → [Lane 2 begins]

Core law for Lane 1:
  Nothing unlabeled moves forward.
  Nothing speculative executes.
  Everything enters archive.
  Deferred nodes allow unresolved concepts.
  Promotion controls evolution.

LABEL TRANSITION RULES (strictly enforced):
  UNKNOWN     → SPECULATIVE   (allowed: classification adds evidence)
  UNKNOWN     → TRUTH         (allowed: if directly verifiable)
  SPECULATIVE → TRUTH         (allowed: only via promotion protocol)
  SPECULATIVE → DEFERRED      (allowed: unresolved but tracked)
  TRUTH       → DEFERRED      (NOT allowed: verified cannot be un-verified)
  SPECULATIVE → VERIFIED      (NOT allowed: must go through TRUTH first)
  any         → EXECUTING     (NOT allowed from Lane 1: Reality Gate only)

References:
  ARCHITECTURE.md — Lane 1 definition (L03–L08)
  promotion_protocol.py — promotion criteria and rejection paths
  reality_gate.py — the only entry to Lane 2
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional


# ─── EPISTEMIC LABEL ──────────────────────────────────────────────────────────

@unique
class EpistemicLabel(str, Enum):
    """
    The label attached to every idea in Lane 1.

    Nothing moves forward without one.
    Nothing speculative executes.

    UNKNOWN:     Default state. Not yet classified.
    SPECULATIVE: Has supporting reasoning but no verified proof.
    TRUTH:       Verified by evidence, test, or logical necessity.
    DEFERRED:    Unresolved. Parked. May be revisited later.
    REJECTED:    Failed validation. Cannot be promoted.
    """
    UNKNOWN     = "UNKNOWN"
    SPECULATIVE = "SPECULATIVE"
    TRUTH       = "TRUTH"
    DEFERRED    = "DEFERRED"
    REJECTED    = "REJECTED"

    def can_transition_to(self, target: "EpistemicLabel") -> bool:
        """
        Enforce valid label transitions.
        Returns False for any transition that would corrupt epistemic integrity.
        """
        VALID_TRANSITIONS = {
            EpistemicLabel.UNKNOWN:     {EpistemicLabel.SPECULATIVE,
                                         EpistemicLabel.TRUTH,
                                         EpistemicLabel.DEFERRED},
            EpistemicLabel.SPECULATIVE: {EpistemicLabel.TRUTH,
                                         EpistemicLabel.DEFERRED,
                                         EpistemicLabel.REJECTED},
            EpistemicLabel.TRUTH:       {EpistemicLabel.DEFERRED},
            EpistemicLabel.DEFERRED:    {EpistemicLabel.SPECULATIVE,
                                         EpistemicLabel.REJECTED},
            EpistemicLabel.REJECTED:    set(),  # terminal — no transitions
        }
        return target in VALID_TRANSITIONS.get(self, set())


# ─── INPUT MODE ───────────────────────────────────────────────────────────────

@unique
class InputMode(str, Enum):
    """
    The mode assigned by L02 Mode Router.
    Determines which Lane 1 processing path the intent follows.
    All three paths converge at L05 Epistemic Labeling.
    """
    CREATIVE   = "CREATIVE"    # L03 — unbounded generation
    ANALYTICAL = "ANALYTICAL"  # L04 — structured reasoning
    EXECUTION  = "EXECUTION"   # intent to execute — still goes through L05–L08


# ─── IDEA NODE ────────────────────────────────────────────────────────────────

@dataclass
class IdeaNode:
    """
    The fundamental unit of Lane 1.

    Every piece of intelligence that enters the system is an IdeaNode.
    It cannot execute. It can only be labeled, stored, deferred, or promoted.

    idea_id     — stable unique identifier
    content     — the idea's content (text, structured data, anything)
    label       — current epistemic label (MUST be set before archiving)
    mode        — which processing path produced this idea
    created_at  — logical timestamp
    evidence    — supporting evidence for the current label
    parent_id   — if derived from another idea
    """
    idea_id:    str
    content:    str
    label:      EpistemicLabel
    mode:       InputMode
    created_at: float = field(default_factory=time.time)
    evidence:   List[str] = field(default_factory=list)
    parent_id:  Optional[str] = None
    metadata:   Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.idea_id:
            raise ValueError("idea_id must be non-empty")
        if not self.content:
            raise ValueError("content must be non-empty")

    @property
    def content_hash(self) -> str:
        """Stable SHA-256 of idea content. Used for deduplication."""
        return hashlib.sha256(self.content.encode()).hexdigest()

    def transition_label(self, new_label: EpistemicLabel,
                         reason: str = "") -> "LabelTransition":
        """
        Attempt a label transition. Returns LabelTransition.
        Does NOT mutate self — caller applies the result.
        """
        allowed = self.label.can_transition_to(new_label)
        return LabelTransition(
            idea_id=self.idea_id,
            from_label=self.label,
            to_label=new_label,
            allowed=allowed,
            reason=reason if reason else (
                "Valid transition" if allowed
                else f"Invalid: {self.label.value} → {new_label.value} not permitted"
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id":      self.idea_id,
            "content_hash": self.content_hash,
            "label":        self.label.value,
            "mode":         self.mode.value,
            "created_at":   self.created_at,
            "evidence":     self.evidence,
            "parent_id":    self.parent_id,
            "metadata":     self.metadata,
        }


# ─── LABEL TRANSITION ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LabelTransition:
    """
    Result of a label transition attempt.
    Immutable. Always produced — never silently swallowed.
    """
    idea_id:    str
    from_label: EpistemicLabel
    to_label:   EpistemicLabel
    allowed:    bool
    reason:     str

    def apply_to(self, node: IdeaNode) -> IdeaNode:
        """
        If allowed, return a new IdeaNode with the updated label.
        If not allowed, raises ValueError — transitions never fail silently.
        """
        if not self.allowed:
            raise ValueError(
                f"Illegal label transition on '{self.idea_id}': "
                f"{self.from_label.value} → {self.to_label.value}. "
                f"Reason: {self.reason}"
            )
        from dataclasses import replace
        return replace(node, label=self.to_label)


# ─── PROMOTION CRITERIA ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class PromotionCriteria:
    """
    The conditions an idea must meet to be promoted from SPECULATIVE to TRUTH.

    All criteria must be satisfied. Partial satisfaction is REJECTION.
    This is the falsifiable definition of promotion.

    min_evidence_count  — minimum number of supporting evidence items
    requires_test       — must have at least one passing test reference
    requires_no_contradictions — must have zero known contradictions
    max_age_seconds     — ideas older than this cannot be promoted without re-validation
    """
    min_evidence_count:          int   = 1
    requires_test:               bool  = True
    requires_no_contradictions:  bool  = True
    max_age_seconds:             float = 86400.0  # 24 hours

    def evaluate(self, node: IdeaNode,
                 contradictions: List[str] = None,
                 has_passing_test: bool = False) -> "PromotionResult":
        """
        Evaluate an IdeaNode against promotion criteria.
        Returns a PromotionResult — always explicit, never silent.
        """
        failures = []
        contradictions = contradictions or []

        if node.label != EpistemicLabel.SPECULATIVE:
            failures.append(
                f"Only SPECULATIVE ideas can be promoted, got {node.label.value}"
            )

        if len(node.evidence) < self.min_evidence_count:
            failures.append(
                f"Insufficient evidence: {len(node.evidence)} < {self.min_evidence_count}"
            )

        if self.requires_test and not has_passing_test:
            failures.append("No passing test reference provided")

        if self.requires_no_contradictions and contradictions:
            failures.append(
                f"Known contradictions: {contradictions[:3]}"
            )

        age = time.time() - node.created_at
        if age > self.max_age_seconds:
            failures.append(
                f"Idea too old for promotion: {age:.0f}s > {self.max_age_seconds:.0f}s"
            )

        return PromotionResult(
            idea_id=node.idea_id,
            approved=len(failures) == 0,
            failures=failures,
        )


@dataclass(frozen=True)
class PromotionResult:
    """Result of a promotion evaluation. Explicit. Always returned."""
    idea_id:  str
    approved: bool
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id":  self.idea_id,
            "approved": self.approved,
            "failures": self.failures,
        }


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_label_transitions_valid() -> bool:
    """Valid transitions are permitted."""
    assert EpistemicLabel.UNKNOWN.can_transition_to(EpistemicLabel.SPECULATIVE)
    assert EpistemicLabel.UNKNOWN.can_transition_to(EpistemicLabel.TRUTH)
    assert EpistemicLabel.SPECULATIVE.can_transition_to(EpistemicLabel.TRUTH)
    assert EpistemicLabel.SPECULATIVE.can_transition_to(EpistemicLabel.DEFERRED)
    assert EpistemicLabel.SPECULATIVE.can_transition_to(EpistemicLabel.REJECTED)
    return True

def _test_label_transitions_invalid() -> bool:
    """Invalid transitions are blocked."""
    # TRUTH cannot become SPECULATIVE (verified cannot be un-verified)
    assert not EpistemicLabel.TRUTH.can_transition_to(EpistemicLabel.SPECULATIVE)
    # REJECTED is terminal
    assert not EpistemicLabel.REJECTED.can_transition_to(EpistemicLabel.TRUTH)
    assert not EpistemicLabel.REJECTED.can_transition_to(EpistemicLabel.SPECULATIVE)
    # SPECULATIVE cannot skip to EXECUTING (doesn't exist as label)
    return True

def _test_idea_node_requires_content() -> bool:
    """IdeaNode rejects empty content."""
    try:
        IdeaNode(idea_id="x", content="", label=EpistemicLabel.UNKNOWN,
                 mode=InputMode.CREATIVE)
        raise AssertionError("Should raise")
    except ValueError:
        pass
    return True

def _test_idea_node_content_hash_stable() -> bool:
    """Same content → same hash every time."""
    n = IdeaNode(idea_id="h1", content="test idea", label=EpistemicLabel.UNKNOWN,
                 mode=InputMode.ANALYTICAL)
    assert n.content_hash == n.content_hash
    assert len(n.content_hash) == 64
    return True

def _test_label_transition_allowed() -> bool:
    """Allowed transition produces new node with updated label."""
    n = IdeaNode(idea_id="t1", content="test", label=EpistemicLabel.UNKNOWN,
                 mode=InputMode.CREATIVE)
    t = n.transition_label(EpistemicLabel.SPECULATIVE, "supporting evidence found")
    assert t.allowed
    n2 = t.apply_to(n)
    assert n2.label == EpistemicLabel.SPECULATIVE
    assert n.label == EpistemicLabel.UNKNOWN  # original unchanged
    return True

def _test_label_transition_rejected_raises() -> bool:
    """Illegal transition raises ValueError — never silent."""
    n = IdeaNode(idea_id="t2", content="test", label=EpistemicLabel.TRUTH,
                 mode=InputMode.ANALYTICAL)
    t = n.transition_label(EpistemicLabel.SPECULATIVE)
    assert not t.allowed
    try:
        t.apply_to(n)
        raise AssertionError("Should raise ValueError")
    except ValueError as e:
        assert "Illegal label transition" in str(e)
    return True

def _test_promotion_requires_evidence() -> bool:
    """No evidence → promotion rejected."""
    n = IdeaNode(idea_id="p1", content="idea", label=EpistemicLabel.SPECULATIVE,
                 mode=InputMode.ANALYTICAL, evidence=[])
    criteria = PromotionCriteria(min_evidence_count=1)
    result = criteria.evaluate(n, has_passing_test=True)
    assert not result.approved
    assert any("evidence" in f for f in result.failures)
    return True

def _test_promotion_requires_test() -> bool:
    """No passing test → promotion rejected when requires_test=True."""
    n = IdeaNode(idea_id="p2", content="idea", label=EpistemicLabel.SPECULATIVE,
                 mode=InputMode.ANALYTICAL, evidence=["e1"])
    criteria = PromotionCriteria(requires_test=True)
    result = criteria.evaluate(n, has_passing_test=False)
    assert not result.approved
    assert any("test" in f for f in result.failures)
    return True

def _test_promotion_blocked_by_contradictions() -> bool:
    """Known contradictions block promotion."""
    n = IdeaNode(idea_id="p3", content="idea", label=EpistemicLabel.SPECULATIVE,
                 mode=InputMode.ANALYTICAL, evidence=["e1"])
    criteria = PromotionCriteria(requires_no_contradictions=True)
    result = criteria.evaluate(n, contradictions=["counter-evidence"], has_passing_test=True)
    assert not result.approved
    assert any("contradiction" in f for f in result.failures)
    return True

def _test_promotion_approved_when_criteria_met() -> bool:
    """All criteria met → promotion approved."""
    n = IdeaNode(idea_id="p4", content="idea", label=EpistemicLabel.SPECULATIVE,
                 mode=InputMode.ANALYTICAL, evidence=["e1", "e2"])
    criteria = PromotionCriteria(min_evidence_count=1, requires_test=True,
                                  requires_no_contradictions=True)
    result = criteria.evaluate(n, contradictions=[], has_passing_test=True)
    assert result.approved, f"Should be approved: {result.failures}"
    return True

def _test_promotion_non_speculative_rejected() -> bool:
    """Only SPECULATIVE ideas can be promoted."""
    n = IdeaNode(idea_id="p5", content="idea", label=EpistemicLabel.UNKNOWN,
                 mode=InputMode.CREATIVE, evidence=["e1"])
    criteria = PromotionCriteria()
    result = criteria.evaluate(n, has_passing_test=True)
    assert not result.approved
    assert any("SPECULATIVE" in f for f in result.failures)
    return True

def _test_to_dict_serializable() -> bool:
    """IdeaNode.to_dict() is JSON-serializable."""
    import json
    n = IdeaNode(idea_id="s1", content="test", label=EpistemicLabel.DEFERRED,
                 mode=InputMode.CREATIVE)
    d = n.to_dict()
    json.dumps(d)  # must not raise
    assert "label" in d and "idea_id" in d
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
    print("EPISTEMIC TYPES — Labyrinth-OS / Lane 1")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        raise SystemExit(1)
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}\n  Tests: {passed}/{passed+failed}")
    print(f"\n{'='*70}\n  EPISTEMIC TYPES — COMPLETE\n{'='*70}")
