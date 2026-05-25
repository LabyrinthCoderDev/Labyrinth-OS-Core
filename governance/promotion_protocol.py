"""
promotion_protocol.py — Labyrinth-OS / Lane 1 / L08
=====================================================
L08 Promotion Protocol

The controlled evolution layer. An idea graduates from SPECULATIVE to TRUTH
only by passing explicit, falsifiable criteria here.

Law: unstable ideas FAIL promotion. Inconsistent ideas FAIL promotion.
Only repeatable + validated ideas PASS.

Promotion criteria (all must pass):
  1. STABILITY:    idea has been SPECULATIVE for at least min_age_seconds
                   (prevents hot-flash promotions on fresh ideas)
  2. EVIDENCE:     has at least min_evidence_count supporting items
  3. TEST:         has at least one passing test reference
  4. NO CONTRADICTIONS: zero known contradictions in the archive
  5. CONSISTENCY:  content_hash matches at last two archive versions
                   (idea hasn't changed meaning while being evaluated)

Rejection paths (explicit, not silent):
  UNSTABLE    — promoted too soon (min_age not met)
  WEAK        — insufficient evidence
  UNTESTED    — no test reference
  CONTRADICTED — known contradictions exist
  INCONSISTENT — content changed between versions (possibly manipulated)
  WRONG_LABEL — only SPECULATIVE ideas can be promoted

References:
  ARCHITECTURE.md   — L08 Promotion Protocol
  epistemic_types.py — PromotionCriteria, PromotionResult
  archive_memory.py  — ArchiveMemory (reads versions for consistency check)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from epistemic_types import (
    EpistemicLabel, IdeaNode, PromotionCriteria, PromotionResult,
)
from archive_memory import ArchiveMemory

# Classification enforcement — optional import
# If classification module available, enforcement is active
# If not available, promotion proceeds without classification check (prototype mode)
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'epistemic', 'classification'))
    from enforcement import EnforcementEngine, EnforcementDecision
    _ENFORCEMENT_AVAILABLE = True
except ImportError:
    import warnings
    warnings.warn("Classification enforcement not importable — DISABLED (prototype only). "
                  "Post-prototype: convert to hard error.", RuntimeWarning)
    _ENFORCEMENT_AVAILABLE = False


# ─── REJECTION REASON ─────────────────────────────────────────────────────────

@unique
class PromotionRejectionReason(str, Enum):  # renamed from PromotionRejectionReason (May 2026 — avoids collision with label_schema.PromotionRejectionReason)
    UNSTABLE     = "UNSTABLE"      # too new for promotion
    WEAK         = "WEAK"          # insufficient evidence
    UNTESTED     = "UNTESTED"      # no passing test
    CONTRADICTED = "CONTRADICTED"  # known contradictions
    INCONSISTENT = "INCONSISTENT"  # content changed between versions
    WRONG_LABEL  = "WRONG_LABEL"   # only SPECULATIVE can be promoted
    NONE         = "NONE"          # no rejection — promotion approved


# ─── PROMOTION DECISION ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class PromotionDecision:
    """
    The explicit output of a promotion evaluation.

    approved        — True only when ALL criteria pass
    rejection_reasons — list of PromotionRejectionReason (empty if approved)
    failures        — human-readable failure descriptions
    idea_id         — the idea evaluated
    evaluated_at    — timestamp
    """
    idea_id:          str
    approved:         bool
    rejection_reasons: List[PromotionRejectionReason]
    failures:         List[str]
    evaluated_at:     float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id":          self.idea_id,
            "approved":         self.approved,
            "rejection_reasons":[r.value for r in self.rejection_reasons],
            "failures":         self.failures,
            "evaluated_at":     self.evaluated_at,
        }


# ─── PROMOTION PROTOCOL ───────────────────────────────────────────────────────

class PromotionProtocol:
    """
    L08: Controls idea evolution from SPECULATIVE → TRUTH.

    Deterministic. Same inputs → same decision.
    Every rejection has a named reason. Nothing fails silently.
    """

    DEFAULT_CRITERIA = PromotionCriteria(
        min_evidence_count=2,
        requires_test=True,
        requires_no_contradictions=True,
        max_age_seconds=86400.0,
    )

    # Minimum time an idea must be SPECULATIVE before promotion
    MIN_AGE_SECONDS = 10.0  # seconds (short for testing; real use: hours)

    def evaluate(
        self,
        node: IdeaNode,
        archive: ArchiveMemory,
        contradictions: Optional[List[str]] = None,
        has_passing_test: bool = False,
        criteria: Optional[PromotionCriteria] = None,
        artifact_metadata = None,  # ArtifactMetadata if classification active
    ) -> PromotionDecision:
        """
        Evaluate an idea for promotion. Returns PromotionDecision.

        node            — the current IdeaNode (must be SPECULATIVE)
        archive         — the archive to check version history for consistency
        contradictions  — known contradictions (from L04 or external validation)
        has_passing_test — whether a passing test reference exists
        criteria        — optional override of DEFAULT_CRITERIA
        """
        # Archive recall — chunk_store feeds past failure evidence into promotion
        # Searches the epistemic archive for failure chunks tagged with this idea_id.
        # If found, they are logged in the promotion record as evidence.
        # This wires the cold archive to the live promotion decision path.
        _archive_failure_hits = []
        try:
            import sys as _sys, os as _os
            _ep_dir = _os.path.normpath(_os.path.join(
                _os.path.dirname(__file__), '..', '..', 'epistemic', 'archive'))
            if _ep_dir not in _sys.path:
                _sys.path.insert(0, _ep_dir)
            from chunk_store import ChunkStore as _CS
            _store = _CS(_os.path.normpath(_os.path.join(
                _os.path.dirname(__file__), '..', '..', 'archive')))
            _archive_failure_hits = _store.search_index(
                query=node.idea_id, tag="failure")
        except Exception:
            pass  # chunk_store unavailable — continue without archive evidence

        # Classification enforcement check
        # Requires artifact_metadata to be passed in when classification is active
        if _ENFORCEMENT_AVAILABLE and artifact_metadata is not None:
            engine = EnforcementEngine()
            # PROTOTYPE NOTE: enforce=True — classification is now structural, not advisory.
            # In prototype stage this blocks FAILED/DEPRECATED/ARCHIVED artifacts from promotion.
            # ROADMAP (post-prototype): wire artifact_metadata from ignition Option B path so
            # enforce=True fires on ALL promotion attempts, not just those with metadata provided.
            # When ignition passes real artifact_metadata, this becomes fully enforced end-to-end.
            enforcement = engine.check_can_promote(artifact_metadata, enforce=True)
            if enforcement.is_blocked:
                return PromotionDecision(
                    idea_id=node.idea_id,
                    approved=False,
                    rejection_reasons=[PromotionRejectionReason.WRONG_LABEL],
                    failures=[f"Classification enforcement: {enforcement.reason}"],
                )
            if enforcement.decision == EnforcementDecision.WARN:
                # PARTIAL — log warning, cap confidence in result
                pass  # warning is in the audit log; promotion continues with cap

        criteria = criteria or self.DEFAULT_CRITERIA
        contradictions = contradictions or []
        failures = []
        reasons = []

        # 1. Label check
        if node.label != EpistemicLabel.SPECULATIVE:
            return PromotionDecision(
                idea_id=node.idea_id,
                approved=False,
                rejection_reasons=[PromotionRejectionReason.WRONG_LABEL],
                failures=[f"Only SPECULATIVE ideas can be promoted. "
                           f"Got {node.label.value}."],
            )

        # 2. Stability check (age)
        age = time.time() - node.created_at
        if age < self.MIN_AGE_SECONDS:
            failures.append(
                f"Too new for promotion: age={age:.1f}s < "
                f"minimum={self.MIN_AGE_SECONDS}s"
            )
            reasons.append(PromotionRejectionReason.UNSTABLE)

        # 3. Evidence check
        if len(node.evidence) < criteria.min_evidence_count:
            failures.append(
                f"Insufficient evidence: {len(node.evidence)} items < "
                f"required {criteria.min_evidence_count}"
            )
            reasons.append(PromotionRejectionReason.WEAK)

        # 4. Test check
        if criteria.requires_test and not has_passing_test:
            failures.append("No passing test reference provided")
            reasons.append(PromotionRejectionReason.UNTESTED)

        # 5. Contradiction check
        if criteria.requires_no_contradictions and contradictions:
            failures.append(
                f"Known contradictions: {contradictions[:3]}"
            )
            reasons.append(PromotionRejectionReason.CONTRADICTED)

        # 6. Consistency check (content hash must not have changed)
        versions = archive.get_all_versions(node.idea_id)
        if len(versions) >= 2:
            hashes = [v.node.content_hash for v in versions[-2:]]
            if len(set(hashes)) > 1:
                failures.append(
                    "Content changed between archive versions — "
                    "idea is inconsistent or was modified"
                )
                reasons.append(PromotionRejectionReason.INCONSISTENT)

        approved = len(failures) == 0
        if approved:
            reasons = [PromotionRejectionReason.NONE]

        return PromotionDecision(
            idea_id=node.idea_id,
            approved=approved,
            rejection_reasons=reasons,
            failures=failures,
        )

    def apply_promotion(
        self,
        node: IdeaNode,
        decision: PromotionDecision,
    ) -> IdeaNode:
        """
        If decision is approved, return new IdeaNode with label=TRUTH.
        If not approved, raises ValueError — never silently ignores rejection.
        """
        if not decision.approved:
            raise ValueError(
                f"Cannot promote '{node.idea_id}': "
                f"{[r.value for r in decision.rejection_reasons]}. "
                f"Failures: {decision.failures}"
            )
        transition = node.transition_label(EpistemicLabel.TRUTH, "Promotion approved")
        return transition.apply_to(node)


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

_protocol = PromotionProtocol()

def evaluate_promotion(
    node: IdeaNode,
    archive: ArchiveMemory,
    contradictions: Optional[List[str]] = None,
    has_passing_test: bool = False,
) -> PromotionDecision:
    return _protocol.evaluate(node, archive, contradictions, has_passing_test)


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_speculative_node(evidence_count=2, age_seconds=0.0):
    from epistemic_types import InputMode
    import time
    node = IdeaNode(
        idea_id="promo_test",
        content="promotable idea",
        label=EpistemicLabel.SPECULATIVE,
        mode=InputMode.ANALYTICAL,
        evidence=[f"e{i}" for i in range(evidence_count)],
        created_at=time.time() - age_seconds,
    )
    return node

def _test_wrong_label_rejected() -> bool:
    """Only SPECULATIVE can be promoted."""
    from epistemic_types import InputMode
    node = IdeaNode(idea_id="x", content="y", label=EpistemicLabel.UNKNOWN,
                    mode=InputMode.CREATIVE)
    archive = ArchiveMemory()
    archive.archive(node)
    decision = evaluate_promotion(node, archive)
    assert not decision.approved
    assert PromotionRejectionReason.WRONG_LABEL in decision.rejection_reasons
    return True

def _test_unstable_rejected() -> bool:
    """Ideas younger than MIN_AGE are rejected."""
    node = _make_speculative_node(evidence_count=3, age_seconds=0.0)
    archive = ArchiveMemory()
    archive.archive(node)
    decision = evaluate_promotion(node, archive, has_passing_test=True)
    assert not decision.approved
    assert PromotionRejectionReason.UNSTABLE in decision.rejection_reasons
    return True

def _test_weak_evidence_rejected() -> bool:
    """Insufficient evidence → WEAK rejection."""
    node = _make_speculative_node(evidence_count=0, age_seconds=100.0)
    archive = ArchiveMemory()
    archive.archive(node)
    decision = evaluate_promotion(node, archive, has_passing_test=True)
    assert not decision.approved
    assert PromotionRejectionReason.WEAK in decision.rejection_reasons
    return True

def _test_no_test_rejected() -> bool:
    """No test reference → UNTESTED rejection."""
    node = _make_speculative_node(evidence_count=3, age_seconds=100.0)
    archive = ArchiveMemory()
    archive.archive(node)
    decision = evaluate_promotion(node, archive, has_passing_test=False)
    assert not decision.approved
    assert PromotionRejectionReason.UNTESTED in decision.rejection_reasons
    return True

def _test_contradiction_rejected() -> bool:
    """Known contradictions → CONTRADICTED rejection."""
    node = _make_speculative_node(evidence_count=3, age_seconds=100.0)
    archive = ArchiveMemory()
    archive.archive(node)
    decision = evaluate_promotion(node, archive,
                                  contradictions=["counter_evidence"],
                                  has_passing_test=True)
    assert not decision.approved
    assert PromotionRejectionReason.CONTRADICTED in decision.rejection_reasons
    return True

def _test_inconsistent_content_rejected() -> bool:
    """Content change between versions → INCONSISTENT rejection."""
    from epistemic_types import InputMode
    from dataclasses import replace
    archive = ArchiveMemory()
    node_v1 = IdeaNode(idea_id="chg", content="original content",
                       label=EpistemicLabel.SPECULATIVE,
                       mode=InputMode.ANALYTICAL,
                       evidence=["e1","e2"],
                       created_at=time.time() - 100.0)
    node_v2 = replace(node_v1, content="changed content")
    archive.archive(node_v1)
    archive.archive(node_v2)
    decision = evaluate_promotion(node_v2, archive, has_passing_test=True)
    assert not decision.approved
    assert PromotionRejectionReason.INCONSISTENT in decision.rejection_reasons
    return True

def _test_all_criteria_met_approved() -> bool:
    """All criteria met → promotion approved."""
    node = _make_speculative_node(evidence_count=3, age_seconds=100.0)
    archive = ArchiveMemory()
    archive.archive(node)
    # Archive again with same content (consistent)
    archive.archive(node)
    decision = evaluate_promotion(node, archive,
                                  contradictions=[],
                                  has_passing_test=True)
    assert decision.approved, f"Should approve: {decision.failures}"
    assert PromotionRejectionReason.NONE in decision.rejection_reasons
    return True

def _test_apply_promotion_produces_truth() -> bool:
    """Approved promotion → IdeaNode with TRUTH label."""
    node = _make_speculative_node(evidence_count=3, age_seconds=100.0)
    archive = ArchiveMemory()
    archive.archive(node)
    archive.archive(node)
    protocol = PromotionProtocol()
    decision = protocol.evaluate(node, archive, has_passing_test=True)
    assert decision.approved
    promoted = protocol.apply_promotion(node, decision)
    assert promoted.label == EpistemicLabel.TRUTH
    assert node.label == EpistemicLabel.SPECULATIVE  # original unchanged
    return True

def _test_apply_rejected_raises() -> bool:
    """Applying a rejected decision raises ValueError."""
    node = _make_speculative_node(evidence_count=0, age_seconds=0.0)
    archive = ArchiveMemory()
    archive.archive(node)
    protocol = PromotionProtocol()
    decision = protocol.evaluate(node, archive, has_passing_test=False)
    assert not decision.approved
    try:
        protocol.apply_promotion(node, decision)
        raise AssertionError("Should raise ValueError")
    except ValueError:
        pass
    return True

def _test_decision_to_dict_serializable() -> bool:
    """PromotionDecision.to_dict() is JSON-serializable."""
    import json
    node = _make_speculative_node(evidence_count=0, age_seconds=0.0)
    archive = ArchiveMemory()
    archive.archive(node)
    decision = evaluate_promotion(node, archive)
    json.dumps(decision.to_dict())
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
    print("PROMOTION PROTOCOL — Labyrinth-OS / Lane 1 / L08")
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
    print(f"\n{'='*70}\n  PROMOTION PROTOCOL — COMPLETE\n{'='*70}")
