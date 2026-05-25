"""
label_schema.py — Labyrinth-OS / Epistemic Labeling Layer (L3.5)
=================================================================
Label types, categories, confidence tiers, and rejection reasons.

All labels that enter the epistemic pipeline must conform to this schema.
Schema violations are rejected before reaching the Reality Gate.

References:
  ARCHITECTURE.md  — L3.5 Labeling (first-class epistemic layer)
  spec/LABELING.md — Formal labeling specification
  INVARIANTS.md    — I11 Labeling closure
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Optional


# ─── LABEL CATEGORY ───────────────────────────────────────────────────────────

@unique
class LabelCategory(str, Enum):
    """
    Epistemic label categories.  Every artifact entering the pipeline
    receives exactly one category.  Only VALID may cross the Reality Gate.
    """
    VALID      = "VALID"       # passed all validation checks
    UNCERTAIN  = "UNCERTAIN"   # below confidence threshold — needs more signal
    REJECTED   = "REJECTED"    # failed validation — must not proceed
    DEFERRED   = "DEFERRED"    # structurally sound but outside current scope


# ─── CONFIDENCE TIER ──────────────────────────────────────────────────────────

@unique
class ConfidenceTier(str, Enum):
    """
    Coarse confidence bucket derived from the numeric [0.0, 1.0] score.

    Mapping (see ConfidenceMeter.tier_for):
      HIGH          ≥ 0.85
      MEDIUM        ≥ 0.60
      LOW           ≥ 0.35
      UNINITIALIZED < 0.35 (or score is None)
    """
    HIGH          = "HIGH"
    MEDIUM        = "MEDIUM"
    LOW           = "LOW"
    UNINITIALIZED = "UNINITIALIZED"


# ─── REJECTION REASON ─────────────────────────────────────────────────────────

@unique
class RejectionReason(str, Enum):
    """Enumerated rejection reasons emitted by LabelValidator."""
    SCHEMA_VIOLATION        = "SCHEMA_VIOLATION"         # required field missing / wrong type
    CONFIDENCE_BELOW_THRESHOLD = "CONFIDENCE_BELOW_THRESHOLD"  # score < PROMOTION_THRESHOLD
    POLICY_VIOLATION        = "POLICY_VIOLATION"         # contradicts a hard policy rule
    STALE_LABEL             = "STALE_LABEL"              # label older than TTL
    ARCHIVE_CONTRADICTION   = "ARCHIVE_CONTRADICTION"    # contradicts archived pattern
    DUPLICATE_LABEL         = "DUPLICATE_LABEL"          # identical label already active
    MISSING_SOURCE          = "MISSING_SOURCE"           # no originating sensor chain


# ─── LABEL RECORD ─────────────────────────────────────────────────────────────

@dataclass
class LabelRecord:
    """
    An epistemic label record — the unit of truth in the labeling layer.

    Fields
    ------
    label_id        Unique identifier (assigned by labeling system)
    category        LabelCategory (VALID | UNCERTAIN | REJECTED | DEFERRED)
    confidence      Float in [0.0, 1.0].  None means UNINITIALIZED.
    source          Module that created this label (e.g., "watcher_a", "council")
    content         Free-form payload (usually stringified CouncilResult or proposal hash)
    timestamp       Unix epoch float when label was created
    ttl_seconds     How long this label is valid.  0 = no expiry.
    rejection_reason Set if category == REJECTED
    metadata        Arbitrary key→value annotations

    Rules
    -----
    - category VALID requires confidence ≥ VALID_CONFIDENCE_FLOOR.
    - category REJECTED requires rejection_reason to be set.
    - label_id must be globally unique (enforced by LabelValidator).
    - Labels are immutable once sealed (hash stored in archive).
    """

    VALID_CONFIDENCE_FLOOR: float = field(default=0.60, init=False, repr=False, compare=False)

    label_id:         str
    category:         LabelCategory
    confidence:       Optional[float]
    source:           str
    content:          str
    timestamp:        float          = field(default_factory=time.time)
    ttl_seconds:      int            = 0
    rejection_reason: Optional[RejectionReason] = None
    metadata:         dict           = field(default_factory=dict)

    # ── computed after construction ────────────────────────────────────────────

    def seal_hash(self) -> str:
        """
        SHA-256 fingerprint of the canonical fields.

        Used by the archive memory store to build the append-only hash chain.
        The hash covers: label_id, category, confidence, source, content,
        timestamp (truncated to ms), and rejection_reason.
        """
        payload = (
            f"{self.label_id}|{self.category.value}|{self.confidence}|"
            f"{self.source}|{self.content}|"
            f"{int(self.timestamp * 1000)}|"
            f"{self.rejection_reason.value if self.rejection_reason else 'NONE'}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def is_expired(self) -> bool:
        """Return True if this label has exceeded its TTL."""
        if self.ttl_seconds == 0:
            return False
        return (time.time() - self.timestamp) > self.ttl_seconds

    def confidence_tier(self) -> ConfidenceTier:
        """Map numeric confidence to a ConfidenceTier bucket."""
        if self.confidence is None:
            return ConfidenceTier.UNINITIALIZED
        if self.confidence >= 0.85:
            return ConfidenceTier.HIGH
        if self.confidence >= 0.60:
            return ConfidenceTier.MEDIUM
        if self.confidence >= 0.35:
            return ConfidenceTier.LOW
        return ConfidenceTier.UNINITIALIZED


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_label_category_values() -> bool:
    assert LabelCategory.VALID in LabelCategory
    assert LabelCategory.REJECTED in LabelCategory
    return True

def _test_confidence_tier_high() -> bool:
    assert ConfidenceTier.HIGH in ConfidenceTier
    return True

def _test_rejection_reason_values() -> bool:
    reasons = list(RejectionReason)
    assert len(reasons) > 0
    return True

def _test_label_record_constructs() -> bool:
    import time
    r = LabelRecord(
        label_id="test_001",
        category=LabelCategory.VALID,
        confidence=0.90,
        source="test",
        content="test content here",
        timestamp=time.time(),
    )
    assert r.label_id == "test_001"
    return True

def _test_seal_hash_deterministic() -> bool:
    import time
    ts = time.time()
    r = LabelRecord(label_id="x", category=LabelCategory.VALID,
                    confidence=0.9, source="test",
                    content="content", timestamp=ts)
    h1 = r.seal_hash()
    h2 = r.seal_hash()
    assert h1 == h2 and len(h1) == 64
    return True

def _test_valid_category_can_execute() -> bool:
    assert LabelCategory.VALID.can_enter_execution         if hasattr(LabelCategory.VALID, 'can_enter_execution')         else LabelCategory.VALID.value == "VALID"
    return True


def run_tests() -> tuple:
    tests = sorted(
        [(n, o) for n, o in globals().items()
         if n.startswith("_test_") and callable(o)],
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
