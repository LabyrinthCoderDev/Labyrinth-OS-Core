"""
gate_function.py — Labyrinth-OS / Reality Gate (L10.5)
======================================================
Pure decision boundary: Label + promotion status → GateDecision.

The Reality Gate is deterministic and has no side effects.  Given identical
inputs it always produces identical outputs.  It enforces I2 (Gate Determinism)
at the epistemic boundary.

Inputs accepted:
  - CouncilResult (or equivalent confidence score)
  - Promotion status (was this label APPROVED by the promotion pipeline?)
  - Confidence score

Output: GateDecision — YES (may cross) or NO (blocked), always with proof.

Non-negotiable:
  - Deterministic: same inputs → same output, always.
  - No side effects.
  - Fail closed: ambiguity → NO.

References:
  ARCHITECTURE.md  — L10.5 Reality Gate
  spec/REALITY_GATE.md — Formal gate specification
  INVARIANTS.md    — I2 Gate Determinism, I10 Fail Closed
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Optional


# ─── GATE VERDICT ─────────────────────────────────────────────────────────────

@unique
class GateVerdict(str, Enum):
    YES = "YES"    # label may cross into CGIR
    NO  = "NO"     # label is blocked


# ─── GATE DECISION ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GateDecision:
    """
    Immutable result of one Reality Gate evaluation.

    Fields
    ------
    verdict           YES or NO.
    label_id          Label evaluated.
    confidence        Confidence at evaluation time.
    promoted          Whether the promotion pipeline approved this label.
    rejection_reason  Populated if verdict == NO.
    decision_hash     SHA-256 fingerprint of the decision (for ledger anchoring).
    timestamp         When the decision was made.
    """
    verdict:          GateVerdict
    label_id:         str
    confidence:       float
    promoted:         bool
    rejection_reason: Optional[str]
    decision_hash:    str
    timestamp:        float

    @property
    def allowed(self) -> bool:
        return self.verdict == GateVerdict.YES


# ─── GATE FUNCTION ────────────────────────────────────────────────────────────

class GateFunction:
    """
    The Reality Gate — pure decision function.

    No state.  No side effects.  Same inputs → same outputs.

    Usage::

        gate = GateFunction()
        decision = gate.evaluate(
            label_id="lbl-001",
            confidence=0.96,
            promoted=True,
        )
        print(decision.allowed)   # True
    """

    #: Minimum confidence required to cross the Reality Gate.
    CONFIDENCE_THRESHOLD: float = 0.85

    def __init__(
        self,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
    ) -> None:
        self._confidence_threshold = confidence_threshold

    # ── public API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        label_id: str,
        confidence: float,
        promoted: bool,
        label_category: str = "VALID",
        timestamp: Optional[float] = None,
    ) -> GateDecision:
        """
        Evaluate whether a label may cross the Reality Gate.

        Parameters
        ----------
        label_id          Label being evaluated.
        confidence        Current confidence score [0, 1].
        promoted          True if promotion pipeline returned APPROVED.
        label_category    Must be "VALID" to cross.
        timestamp         Pinned timestamp (for determinism in tests).

        Returns
        -------
        GateDecision with verdict YES or NO.
        """
        ts = timestamp or time.time()
        rejection_reason: Optional[str] = None

        # Check 1: must be promoted
        if not promoted:
            rejection_reason = "NOT_PROMOTED: label has not completed promotion pipeline"

        # Check 2: category must be VALID
        elif label_category != "VALID":
            rejection_reason = (
                f"INVALID_CATEGORY: only VALID labels may cross; "
                f"got {label_category!r}"
            )

        # Check 3: confidence must meet threshold
        elif confidence < self._confidence_threshold:
            rejection_reason = (
                f"CONFIDENCE_TOO_LOW: {confidence:.3f} < "
                f"threshold {self._confidence_threshold:.3f}"
            )

        verdict = GateVerdict.YES if rejection_reason is None else GateVerdict.NO

        decision_hash = self._compute_hash(
            label_id=label_id,
            confidence=confidence,
            promoted=promoted,
            verdict=verdict.value,
            timestamp=ts,
        )

        return GateDecision(
            verdict=verdict,
            label_id=label_id,
            confidence=confidence,
            promoted=promoted,
            rejection_reason=rejection_reason,
            decision_hash=decision_hash,
            timestamp=ts,
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_hash(
        label_id: str,
        confidence: float,
        promoted: bool,
        verdict: str,
        timestamp: float,
    ) -> str:
        """Deterministic SHA-256 of decision inputs."""
        payload = (
            f"{label_id}|{confidence:.6f}|{promoted}|{verdict}|"
            f"{int(timestamp * 1000)}"
        ).encode()
        return hashlib.sha256(payload).hexdigest()




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_gate_constructs() -> bool:
    gf = GateFunction(); assert gf is not None; return True

def _test_high_confidence_promoted_allowed() -> bool:
    gf = GateFunction(confidence_threshold=0.85)
    decision = gf.evaluate(label_id="lbl", confidence=0.95, promoted=True)
    assert decision.verdict == GateVerdict.YES; return True

def _test_low_confidence_blocked() -> bool:
    gf = GateFunction(confidence_threshold=0.85)
    decision = gf.evaluate(label_id="lbl", confidence=0.50, promoted=True)
    assert decision.verdict == GateVerdict.NO; return True

def _test_not_promoted_blocked() -> bool:
    gf = GateFunction()
    decision = gf.evaluate(label_id="lbl", confidence=0.99, promoted=False)
    assert decision.verdict == GateVerdict.NO; return True

def _test_decision_hash_present() -> bool:
    gf = GateFunction()
    decision = gf.evaluate(label_id="lbl", confidence=0.95, promoted=True)
    assert decision.decision_hash and len(decision.decision_hash) == 64; return True

def _test_verdicts_exist() -> bool:
    assert GateVerdict.YES in GateVerdict
    assert GateVerdict.NO in GateVerdict; return True

def _test_deterministic() -> bool:
    gf = GateFunction()
    import time
    ts = time.time()
    d1 = gf.evaluate("lbl", 0.95, True, timestamp=ts)
    d2 = gf.evaluate("lbl", 0.95, True, timestamp=ts)
    assert d1.decision_hash == d2.decision_hash; return True



def run_tests() -> tuple:
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("_test_") and callable(o)], key=lambda x:x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn(); passed += 1; results.append((name,"PASS",None))
        except Exception as e:
            failed += 1; results.append((name,"FAIL",str(e)))
    return passed, failed, results
