"""
epistemic_labeler.py — Labyrinth-OS / Lane 1 / L05
====================================================
L05 Epistemic Labeling

THE convergence point. Every idea from L03 (Creative), L04 (Analytical),
and direct execution requests all pass through here before anything else.

Nothing unlabeled moves forward. This module enforces that law.

Labeling is:
  - Explicit: every label is assigned with a reason
  - Validated: transition rules are enforced (epistemic_types.py)
  - Auditable: every assignment is recorded
  - Deterministic: same evidence → same label

Label assignment rules:
  TRUTH       — direct verifiable fact, mathematical necessity, passing test
  SPECULATIVE — has supporting reasoning but no definitive proof
  DEFERRED    — insufficient evidence to classify now; park and revisit
  UNKNOWN     — default; should not persist past this layer

The labeler does NOT decide what is true.
It decides how confident we are and enforces that classification.

References:
  ARCHITECTURE.md   — L05 Epistemic Labeling
  epistemic_types.py — EpistemicLabel, LabelTransition rules
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from epistemic_types import (
    EpistemicLabel, IdeaNode, LabelTransition,
)


# ─── LABEL ASSIGNMENT ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LabelAssignment:
    """
    A single labeling decision.
    Immutable. Always explicit — no silent assignments.
    """
    idea_id:    str
    label:      EpistemicLabel
    reason:     str
    confidence: float           # 0.0–1.0
    assigned_at: float = field(default_factory=time.time)
    evidence:   List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id":     self.idea_id,
            "label":       self.label.value,
            "reason":      self.reason,
            "confidence":  round(self.confidence, 4),
            "assigned_at": self.assigned_at,
            "evidence":    self.evidence,
        }


# ─── LABEL VALIDATION RESULT ──────────────────────────────────────────────────

@dataclass(frozen=True)
class LabelValidationResult:
    """
    Result of validating a proposed label transition.
    Always returned — transitions never fail silently.
    """
    valid:       bool
    from_label:  EpistemicLabel
    to_label:    EpistemicLabel
    reason:      str

    @property
    def is_invalid_transition(self) -> bool:
        return not self.valid


# ─── EPISTEMIC LABELER ────────────────────────────────────────────────────────

class EpistemicLabeler:
    """
    L05: Assigns and validates epistemic labels.

    Two operations:
      assign(node, proposed_label, evidence, reason) → LabelAssignment
      validate_transition(node, target_label) → LabelValidationResult

    assign() does not mutate the node. It returns an assignment record.
    The caller applies the assignment to produce a new IdeaNode.

    Fail closed: ambiguous or insufficient evidence → DEFERRED, not TRUTH.
    """

    # Minimum confidence to assign TRUTH
    TRUTH_MIN_CONFIDENCE = 0.80

    # Minimum confidence to assign SPECULATIVE (below → DEFERRED)
    SPECULATIVE_MIN_CONFIDENCE = 0.40

    def assign(
        self,
        node: IdeaNode,
        proposed_label: EpistemicLabel,
        evidence: List[str],
        reason: str,
        confidence: float,
    ) -> tuple[LabelAssignment, IdeaNode]:
        """
        Assign a label to a node. Enforces transition rules and confidence floors.

        Returns (LabelAssignment, updated_IdeaNode).
        If the proposed label is overridden (e.g. insufficient confidence),
        the actual assigned label may differ from proposed.

        Fail closed:
          - TRUTH with confidence < TRUTH_MIN_CONFIDENCE → downgraded to SPECULATIVE
          - SPECULATIVE with confidence < SPECULATIVE_MIN_CONFIDENCE → DEFERRED
          - Any invalid transition → DEFERRED (never error-out)
        """
        actual_label = proposed_label
        actual_reason = reason

        # Validate transition
        validation = self.validate_transition(node, proposed_label)
        if not validation.valid:
            actual_label = EpistemicLabel.DEFERRED
            actual_reason = (
                f"Invalid transition blocked: {validation.reason}. "
                f"Defaulting to DEFERRED."
            )

        # Confidence floors
        elif proposed_label == EpistemicLabel.TRUTH:
            if confidence < self.TRUTH_MIN_CONFIDENCE:
                actual_label = EpistemicLabel.SPECULATIVE
                actual_reason = (
                    f"Insufficient confidence for TRUTH ({confidence:.2f} < "
                    f"{self.TRUTH_MIN_CONFIDENCE}). Assigned SPECULATIVE."
                )

        elif proposed_label == EpistemicLabel.SPECULATIVE:
            if confidence < self.SPECULATIVE_MIN_CONFIDENCE:
                actual_label = EpistemicLabel.DEFERRED
                actual_reason = (
                    f"Insufficient confidence for SPECULATIVE ({confidence:.2f} < "
                    f"{self.SPECULATIVE_MIN_CONFIDENCE}). Assigned DEFERRED."
                )

        assignment = LabelAssignment(
            idea_id=node.idea_id,
            label=actual_label,
            reason=actual_reason,
            confidence=max(0.0, min(1.0, confidence)),
            evidence=list(evidence),
        )

        # Apply to node
        from dataclasses import replace
        updated_node = replace(
            node,
            label=actual_label,
            evidence=list(set(node.evidence + list(evidence))),
        )

        return assignment, updated_node

    def validate_transition(
        self,
        node: IdeaNode,
        target_label: EpistemicLabel,
    ) -> LabelValidationResult:
        """
        Check whether a label transition is allowed.
        Does NOT apply the transition — validation only.
        """
        transition = node.transition_label(target_label)
        return LabelValidationResult(
            valid=transition.allowed,
            from_label=node.label,
            to_label=target_label,
            reason=transition.reason,
        )

    def classify_from_content(
        self,
        node: IdeaNode,
        has_test: bool = False,
        has_contradiction: bool = False,
        evidence: Optional[List[str]] = None,
    ) -> tuple[LabelAssignment, IdeaNode]:
        """
        Auto-classify based on available signals. Conservative.

        has_test + no contradiction → SPECULATIVE (not TRUTH — labeler doesn't verify)
        has_contradiction           → DEFERRED
        no signals                  → DEFERRED (insufficient to classify)
        """
        evidence = evidence or []

        if has_contradiction:
            return self.assign(
                node, EpistemicLabel.DEFERRED, evidence,
                "Contradiction present — deferred for resolution",
                confidence=0.3,
            )

        if has_test and evidence:
            return self.assign(
                node, EpistemicLabel.SPECULATIVE, evidence,
                "Test reference and evidence present — classified SPECULATIVE",
                confidence=0.65,
            )

        if evidence:
            return self.assign(
                node, EpistemicLabel.SPECULATIVE, evidence,
                "Evidence present but no test — classified SPECULATIVE",
                confidence=0.50,
            )

        return self.assign(
            node, EpistemicLabel.DEFERRED, evidence,
            "Insufficient signals — deferred for further classification",
            confidence=0.2,
        )


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

_labeler = EpistemicLabeler()

def assign_label(
    node: IdeaNode,
    label: EpistemicLabel,
    evidence: List[str],
    reason: str,
    confidence: float,
) -> tuple[LabelAssignment, IdeaNode]:
    return _labeler.assign(node, label, evidence, reason, confidence)

def validate_transition(
    node: IdeaNode,
    target: EpistemicLabel,
) -> LabelValidationResult:
    return _labeler.validate_transition(node, target)


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_node(label=EpistemicLabel.UNKNOWN):
    from epistemic_types import InputMode
    return IdeaNode(
        idea_id="test_node", content="test idea",
        label=label, mode=InputMode.ANALYTICAL,
    )

def _test_truth_assigned_with_high_confidence() -> bool:
    """TRUTH assigned when confidence >= threshold."""
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, updated = labeler.assign(
        node, EpistemicLabel.TRUTH, ["verified test"], "proven", 0.90
    )
    assert assignment.label == EpistemicLabel.TRUTH
    assert updated.label == EpistemicLabel.TRUTH
    return True

def _test_truth_downgraded_low_confidence() -> bool:
    """TRUTH with low confidence → SPECULATIVE (fail closed)."""
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, updated = labeler.assign(
        node, EpistemicLabel.TRUTH, [], "weak claim", 0.50
    )
    assert assignment.label == EpistemicLabel.SPECULATIVE, \
        f"Expected SPECULATIVE, got {assignment.label}"
    return True

def _test_speculative_downgraded_very_low_confidence() -> bool:
    """SPECULATIVE with very low confidence → DEFERRED."""
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, updated = labeler.assign(
        node, EpistemicLabel.SPECULATIVE, [], "very weak", 0.20
    )
    assert assignment.label == EpistemicLabel.DEFERRED
    return True

def _test_invalid_transition_defaults_to_deferred() -> bool:
    """Illegal transition → DEFERRED (never crashes)."""
    node = _make_node(EpistemicLabel.TRUTH)
    labeler = EpistemicLabeler()
    assignment, updated = labeler.assign(
        node, EpistemicLabel.SPECULATIVE, [], "trying to un-verify", 0.9
    )
    assert assignment.label == EpistemicLabel.DEFERRED
    assert "blocked" in assignment.reason.lower()
    return True

def _test_validate_transition_valid() -> bool:
    """Valid transition returns valid=True."""
    node = _make_node()
    result = validate_transition(node, EpistemicLabel.SPECULATIVE)
    assert result.valid
    return True

def _test_validate_transition_invalid() -> bool:
    """Invalid transition returns valid=False with reason."""
    node = _make_node(EpistemicLabel.REJECTED)
    result = validate_transition(node, EpistemicLabel.TRUTH)
    assert not result.valid
    assert result.reason
    return True

def _test_classify_from_content_contradiction_deferred() -> bool:
    """Contradiction → DEFERRED."""
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, _ = labeler.classify_from_content(
        node, has_contradiction=True, evidence=["e1"]
    )
    assert assignment.label == EpistemicLabel.DEFERRED
    return True

def _test_classify_no_signals_deferred() -> bool:
    """No signals → DEFERRED (insufficient to classify)."""
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, _ = labeler.classify_from_content(node)
    assert assignment.label == EpistemicLabel.DEFERRED
    return True

def _test_classify_with_test_and_evidence_speculative() -> bool:
    """Test + evidence → SPECULATIVE (labeler doesn't verify, only classifies)."""
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, _ = labeler.classify_from_content(
        node, has_test=True, evidence=["test_passed"]
    )
    assert assignment.label == EpistemicLabel.SPECULATIVE
    return True

def _test_assignment_to_dict_serializable() -> bool:
    """LabelAssignment.to_dict() is JSON-serializable."""
    import json
    node = _make_node()
    labeler = EpistemicLabeler()
    assignment, _ = labeler.assign(
        node, EpistemicLabel.SPECULATIVE, ["e1"], "test", 0.7
    )
    json.dumps(assignment.to_dict())
    return True

def _test_original_node_not_mutated() -> bool:
    """assign() returns new node — original is not mutated."""
    node = _make_node()
    labeler = EpistemicLabeler()
    _, updated = labeler.assign(
        node, EpistemicLabel.SPECULATIVE, [], "test", 0.7
    )
    assert node.label == EpistemicLabel.UNKNOWN
    assert updated.label == EpistemicLabel.SPECULATIVE
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
    print("EPISTEMIC LABELER — Labyrinth-OS / Lane 1 / L05")
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
    print(f"\n{'='*70}\n  EPISTEMIC LABELER — COMPLETE\n{'='*70}")
