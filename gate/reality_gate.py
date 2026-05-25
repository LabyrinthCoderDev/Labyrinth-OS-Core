"""
reality_gate.py — Labyrinth-OS / Lane 1 / L09
===============================================
L09 Reality Gate

THE ONLY ENTRY POINT FROM LANE 1 INTO LANE 2.

An idea that has not passed the Reality Gate cannot enter execution.
No bypass. No shortcuts. No exceptions.

What the Reality Gate checks:
  1. LABEL: idea must be TRUTH (not SPECULATIVE, not DEFERRED, not UNKNOWN)
  2. EVIDENCE: must have at least one evidence item
  3. PROOF: must have a proof reference (test, formal proof, or verified fact)
  4. NO ACTIVE CONTRADICTIONS: no unresolved contradictions
  5. INTENT CONSISTENCY: the content is consistent with what was archived

What the Reality Gate produces:
  If PASS → a GatePassage that can be handed to Lane 2 (CGIR pipeline)
  If FAIL → a GateBlock with explicit reason — always explicit, never silent

The Reality Gate does NOT execute anything.
It produces a GatePassage that authorizes Lane 2 to begin.

Critical rule:
  Creativity never directly executes.
  Execution never bypasses validation.
  The Reality Gate is where those two laws meet.

References:
  ARCHITECTURE.md   — L09 Reality Gate
  epistemic_types.py — EpistemicLabel
  archive_memory.py  — ArchiveMemory (checks version consistency)
  [Lane 2 begins after GatePassage is handed to CGIR compiler]
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional

from epistemic_types import EpistemicLabel, IdeaNode
from archive_memory import ArchiveMemory

# Classification enforcement
try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'epistemic', 'classification'))
    from enforcement import EnforcementEngine
    _ENFORCEMENT_AVAILABLE = True
except ImportError:
    import warnings
    pass  # Classification enforcement optional in Sentinel-Core
    _ENFORCEMENT_AVAILABLE = False


# ─── GATE RESULT ──────────────────────────────────────────────────────────────

@unique
class GateBlockReason(str, Enum):
    WRONG_LABEL      = "WRONG_LABEL"       # not TRUTH
    NO_EVIDENCE      = "NO_EVIDENCE"       # no supporting evidence
    NO_PROOF         = "NO_PROOF"          # no proof reference
    CONTRADICTED     = "CONTRADICTED"      # unresolved contradictions
    NOT_ARCHIVED     = "NOT_ARCHIVED"      # idea not in archive
    INCONSISTENT     = "INCONSISTENT"      # content drift detected


@dataclass(frozen=True)
class GatePassage:
    """
    Authorization for an idea to enter Lane 2.
    Produced only when ALL Reality Gate checks pass.

    passage_id  — stable hash of (idea_id + content_hash + timestamp)
    idea_id     — the idea being authorized
    content     — the exact content being authorized (frozen at passage time)
    content_hash — SHA-256 of content (Lane 2 must verify this matches)
    issued_at   — when the passage was issued
    """
    passage_id:   str
    idea_id:      str
    content:      str
    content_hash: str
    issued_at:    float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passage_id":   self.passage_id,
            "idea_id":      self.idea_id,
            "content_hash": self.content_hash,
            "issued_at":    self.issued_at,
        }

    @staticmethod
    def compute_id(idea_id: str, content_hash: str, issued_at: float) -> str:
        payload = f"{idea_id}:{content_hash}:{issued_at:.6f}"
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class GateBlock:
    """
    Rejection from the Reality Gate. Always explicit.
    reason     — machine-readable RejectionReason
    detail     — human-readable explanation
    idea_id    — the idea that was rejected
    blocked_at — timestamp
    """
    idea_id:    str
    reason:     GateBlockReason
    detail:     str
    blocked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id":    self.idea_id,
            "reason":     self.reason.value,
            "detail":     self.detail,
            "blocked_at": self.blocked_at,
        }


# ─── REALITY GATE ─────────────────────────────────────────────────────────────

class RealityGate:
    """
    L09: The only entry point from Lane 1 into Lane 2.

    check(node, archive, proof_ref, contradictions) → GatePassage | GateBlock

    Never raises. Always returns one of the two — never None.
    If something is wrong, it's a GateBlock. Always.
    """

    def check(
        self,
        node: IdeaNode,
        archive: ArchiveMemory,
        proof_ref: Optional[str] = None,
        contradictions: Optional[List[str]] = None,
        artifact_metadata = None,  # ArtifactMetadata if classification active
    ) -> "GatePassage | GateBlock":
        """
        Run all Reality Gate checks. Returns GatePassage or GateBlock.

        node           — the IdeaNode attempting to enter Lane 2
        archive        — archive to verify the idea is properly stored
        proof_ref      — a reference to a test, formal proof, or verified fact
        contradictions — any unresolved contradictions
        """
        contradictions = contradictions or []
        issued_at = time.time()

        # Classification enforcement (if artifact_metadata provided)
        if _ENFORCEMENT_AVAILABLE and artifact_metadata is not None:
            engine = EnforcementEngine()
            # PROTOTYPE NOTE: enforce=True — classification is now structural, not advisory.
            # In prototype stage this blocks FAILED/DEPRECATED/ARCHIVED from crossing the gate.
            # ROADMAP (post-prototype): ignition Option B must pass artifact_metadata here so
            # enforcement fires on every real execution attempt, not only those with metadata.
            enforcement = engine.check_can_execute(artifact_metadata, enforce=True)
            if enforcement.is_blocked:
                return GateBlock(
                    idea_id=node.idea_id,
                    reason=GateBlockReason.WRONG_LABEL,
                    detail=f"Classification enforcement: {enforcement.reason}",
                )

        # I16: PromotionReceipt approved=False cannot be upgraded to True here
        # (DeepSeek audit, May 2026 — boundary upgrade prohibition)
        if proof_ref and hasattr(proof_ref, 'approved') and not proof_ref.approved:
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.NO_PROOF,
                detail="I16 VIOLATION: PromotionReceipt.approved=False cannot be "
                       "upgraded to True by the Reality Gate.",
            )

        # Check 1: Must be TRUTH
        if node.label != EpistemicLabel.TRUTH:
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.WRONG_LABEL,
                detail=(
                    f"Reality Gate requires TRUTH label. "
                    f"Got {node.label.value}. "
                    f"Ideas must pass through L08 Promotion Protocol first."
                ),
            )

        # Check 2: Must have evidence
        if not node.evidence:
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.NO_EVIDENCE,
                detail="No supporting evidence. Every TRUTH must have at least one.",
            )

        # Check 3: Must have a proof reference
        if not proof_ref or not proof_ref.strip():
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.NO_PROOF,
                detail=(
                    "No proof reference provided. "
                    "Required: a test name, formal proof identifier, "
                    "or verified fact citation."
                ),
            )

        # Check 4: No active contradictions
        if contradictions:
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.CONTRADICTED,
                detail=f"Unresolved contradictions: {contradictions[:3]}",
            )

        # Check 5: Must be in archive
        archived = archive.get_latest(node.idea_id)
        if archived is None:
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.NOT_ARCHIVED,
                detail=(
                    "Idea not found in archive. "
                    "All ideas must pass through L06 Archive Memory "
                    "before entering the Reality Gate."
                ),
            )

        # Check 6: Content consistency (drift detection)
        if archived.node.content_hash != node.content_hash:
            return GateBlock(
                idea_id=node.idea_id,
                reason=GateBlockReason.INCONSISTENT,
                detail=(
                    f"Content drift detected. "
                    f"Archived hash: {archived.node.content_hash[:12]}… "
                    f"Current hash: {node.content_hash[:12]}… "
                    f"Idea may have been modified after archiving."
                ),
            )

        # All checks passed — issue passage
        passage_id = GatePassage.compute_id(
            node.idea_id, node.content_hash, issued_at
        )
        return GatePassage(
            passage_id=passage_id,
            idea_id=node.idea_id,
            content=node.content,
            content_hash=node.content_hash,
            issued_at=issued_at,
        )


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

_gate = RealityGate()

def check(
    node: IdeaNode,
    archive: ArchiveMemory,
    proof_ref: Optional[str] = None,
    contradictions: Optional[List[str]] = None,
) -> "GatePassage | GateBlock":
    return _gate.check(node, archive, proof_ref, contradictions)


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_truth_node(content="verified idea"):
    from epistemic_types import InputMode
    return IdeaNode(
        idea_id="truth_node",
        content=content,
        label=EpistemicLabel.TRUTH,
        mode=InputMode.ANALYTICAL,
        evidence=["test_passed", "formal_verification"],
    )

def _archived(node):
    archive = ArchiveMemory()
    archive.archive(node)
    return archive

def _test_truth_with_proof_passes() -> bool:
    """TRUTH + evidence + proof + archive → GatePassage."""
    node = _make_truth_node()
    archive = _archived(node)
    result = check(node, archive, proof_ref="test_001")
    assert isinstance(result, GatePassage), f"Expected GatePassage, got {type(result).__name__}: {result}"
    assert len(result.passage_id) == 64
    return True

def _test_wrong_label_blocked() -> bool:
    """Non-TRUTH label → WRONG_LABEL block."""
    from epistemic_types import InputMode
    node = IdeaNode(idea_id="sp", content="x", label=EpistemicLabel.SPECULATIVE,
                    mode=InputMode.ANALYTICAL, evidence=["e1"])
    archive = _archived(node)
    result = check(node, archive, proof_ref="proof")
    assert isinstance(result, GateBlock)
    assert result.reason == GateBlockReason.WRONG_LABEL
    return True

def _test_no_evidence_blocked() -> bool:
    """No evidence → NO_EVIDENCE block."""
    from epistemic_types import InputMode
    node = IdeaNode(idea_id="ne", content="x", label=EpistemicLabel.TRUTH,
                    mode=InputMode.ANALYTICAL, evidence=[])
    archive = _archived(node)
    result = check(node, archive, proof_ref="proof")
    assert isinstance(result, GateBlock)
    assert result.reason == GateBlockReason.NO_EVIDENCE
    return True

def _test_no_proof_blocked() -> bool:
    """No proof reference → NO_PROOF block."""
    node = _make_truth_node()
    archive = _archived(node)
    result = check(node, archive, proof_ref=None)
    assert isinstance(result, GateBlock)
    assert result.reason == GateBlockReason.NO_PROOF
    return True

def _test_contradiction_blocked() -> bool:
    """Active contradiction → CONTRADICTED block."""
    node = _make_truth_node()
    archive = _archived(node)
    result = check(node, archive, proof_ref="proof",
                   contradictions=["counter_evidence"])
    assert isinstance(result, GateBlock)
    assert result.reason == GateBlockReason.CONTRADICTED
    return True

def _test_not_archived_blocked() -> bool:
    """Idea not in archive → NOT_ARCHIVED block."""
    node = _make_truth_node()
    archive = ArchiveMemory()  # empty archive
    result = check(node, archive, proof_ref="proof")
    assert isinstance(result, GateBlock)
    assert result.reason == GateBlockReason.NOT_ARCHIVED
    return True

def _test_content_drift_blocked() -> bool:
    """Content changed after archiving → INCONSISTENT block."""
    from epistemic_types import InputMode
    from dataclasses import replace
    original = _make_truth_node("original content")
    archive = _archived(original)
    # Node content changed
    drifted = replace(original, content="changed content")
    result = check(drifted, archive, proof_ref="proof")
    assert isinstance(result, GateBlock)
    assert result.reason == GateBlockReason.INCONSISTENT
    return True

def _test_passage_id_stable() -> bool:
    """Same inputs → different passage_id (timestamp varies) but always 64 chars."""
    node = _make_truth_node()
    archive = _archived(node)
    r = check(node, archive, proof_ref="proof")
    assert isinstance(r, GatePassage)
    assert len(r.passage_id) == 64
    return True

def _test_passage_content_matches_node() -> bool:
    """GatePassage content matches the maintainerized IdeaNode."""
    node = _make_truth_node()
    archive = _archived(node)
    r = check(node, archive, proof_ref="proof")
    assert isinstance(r, GatePassage)
    assert r.content == node.content
    assert r.content_hash == node.content_hash
    return True

def _test_block_to_dict_serializable() -> bool:
    """GateBlock.to_dict() is JSON-serializable."""
    import json
    node = _make_truth_node()
    archive = _archived(node)
    result = check(node, archive, proof_ref=None)
    assert isinstance(result, GateBlock)
    json.dumps(result.to_dict())
    return True

def _test_passage_to_dict_serializable() -> bool:
    """GatePassage.to_dict() is JSON-serializable."""
    import json
    node = _make_truth_node()
    archive = _archived(node)
    result = check(node, archive, proof_ref="test_001")
    assert isinstance(result, GatePassage)
    json.dumps(result.to_dict())
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
    print("REALITY GATE — Labyrinth-OS / Lane 1 / L09")
    print("The only entry point from Lane 1 into Lane 2.")
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
    print(f"\n{'='*70}\n  REALITY GATE — COMPLETE\n{'='*70}")
