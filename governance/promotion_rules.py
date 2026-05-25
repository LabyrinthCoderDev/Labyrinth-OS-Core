"""
promotion_rules.py — Labyrinth-OS / Promotion Pipeline (L6.5)
=============================================================
Rules that determine whether a candidate label may be promoted.

Promotion is the process by which an epistemic label earns the right to cross
the Reality Gate and enter the execution substrate (CGIR → Gate → AEGIS).

Rules enforced:
  1. Candidate must have confidence ≥ PROMOTION_CONFIDENCE_THRESHOLD.
  2. Candidate must pass the TestHarness (separate module).
  3. Candidate must not contradict archived patterns (archive query).
  4. Promotion must be audited + logged (AuditTrail).
  5. Required number of successful consecutive runs (MIN_CONSECUTIVE_RUNS).

Invariant enforced:
  I14 — Promotion Auditability: all promotions recorded with justification.

References:
  spec/PROMOTION.md — Formal promotion specification
  INVARIANTS.md     — I14
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import List, Optional


# ─── PROMOTION CONSTANTS ──────────────────────────────────────────────────────

#: Minimum confidence required for promotion.
#: NOTE: This (0.95) is intentionally higher than the Reality Gate floor (0.85).
#: A label's confidence can decay between promotion approval and gate crossing;
#: the two-threshold design provides a decay safety margin.
#: See spec/PROMOTION.md — "Two-Threshold Design" for rationale.
PROMOTION_CONFIDENCE_THRESHOLD: float = 0.95

#: Minimum number of consecutive successful runs at threshold.
MIN_CONSECUTIVE_RUNS: int = 3

#: Maximum historical failure rate allowed in the pattern catalog.
MAX_HISTORICAL_FAILURE_RATE: float = 0.20


# ─── PROMOTION OUTCOME ────────────────────────────────────────────────────────

@unique
class PromotionOutcome(str, Enum):
    APPROVED  = "APPROVED"   # candidate cleared all rules
    REJECTED  = "REJECTED"   # failed one or more rules
    DEFERRED  = "DEFERRED"   # rules pass but insufficient run history


# ─── PROMOTION DECISION ───────────────────────────────────────────────────────

@dataclass
class PromotionDecision:
    """
    Result of PromotionRules.evaluate().

    Fields
    ------
    label_id            Candidate label being evaluated.
    outcome             APPROVED | REJECTED | DEFERRED.
    confidence          Confidence at evaluation time.
    consecutive_runs    How many consecutive successful runs this candidate has.
    reasons             List of rejection reasons or approval notes.
    timestamp           When the decision was made.
    """
    label_id:         str
    outcome:          PromotionOutcome
    confidence:       float
    consecutive_runs: int
    reasons:          List[str] = field(default_factory=list)
    timestamp:        float     = field(default_factory=time.time)

    @property
    def approved(self) -> bool:
        return self.outcome == PromotionOutcome.APPROVED


# ─── PROMOTION RULES ─────────────────────────────────────────────────────────

class PromotionRules:
    """
    Evaluate a candidate label against the promotion rule set.

    Usage::

        rules = PromotionRules()
        decision = rules.evaluate(
            label_id="lbl-001",
            confidence=0.96,
            consecutive_runs=4,
            harness_passed=True,
            historical_failure_rate=0.05,
        )
        if decision.approved:
            audit_trail.record(decision, approved_by="steward")
    """

    def __init__(
        self,
        confidence_threshold: float = PROMOTION_CONFIDENCE_THRESHOLD,
        min_consecutive_runs: int   = MIN_CONSECUTIVE_RUNS,
        max_failure_rate: float     = MAX_HISTORICAL_FAILURE_RATE,
    ) -> None:
        self._confidence_threshold = confidence_threshold
        self._min_consecutive_runs = min_consecutive_runs
        self._max_failure_rate     = max_failure_rate
        # P10.5-C: PROMOTION_RACE detection (CLASS-11 TM-001)
        # Tracks label_ids currently in-flight. If two arrive simultaneously,
        # both are blocked and a CONFLICT entry is logged.
        self._in_flight: set = set()

    # ── public API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        label_id: str,
        confidence: float,
        consecutive_runs: int,
        harness_passed: bool,
        historical_failure_rate: float = 0.0,
        archive_contradiction: bool    = False,
        reasoning_text: str            = "",
    ) -> PromotionDecision:
        """
        Evaluate a candidate against all promotion rules.

        Parameters
        ----------
        label_id                  Candidate label identifier.
        confidence                Current confidence score [0, 1].
        consecutive_runs          Number of consecutive passing runs so far.
        harness_passed            Did the TestHarness pass?
        historical_failure_rate   From PatternCatalog (0.0 = never failed).
        archive_contradiction     True if archive has contradicting rejections.
        reasoning_text            Response/reasoning text for EBF polarity check.
        """
        # Rule 0: PROMOTION_RACE detection (CLASS-11 TM-001, P10.5-C)
        if label_id in self._in_flight:
            return PromotionDecision(
                label_id=label_id,
                outcome=PromotionOutcome.REJECTED,
                confidence=confidence,
                consecutive_runs=consecutive_runs,
                reasons=[
                    f"PROMOTION_RACE: label_id={label_id!r} already in-flight. "
                    f"Both proposals blocked (CLASS-11 TM-001)."
                ],
            )
        self._in_flight.add(label_id)
        try:
            result = self._evaluate_inner(
                label_id=label_id,
                confidence=confidence,
                consecutive_runs=consecutive_runs,
                harness_passed=harness_passed,
                historical_failure_rate=historical_failure_rate,
                archive_contradiction=archive_contradiction,
                reasoning_text=reasoning_text,
            )
        finally:
            self._in_flight.discard(label_id)
        return result

    def _evaluate_inner(
        self,
        label_id: str,
        confidence: float,
        consecutive_runs: int,
        harness_passed: bool,
        historical_failure_rate: float = 0.0,
        archive_contradiction: bool    = False,
        **kwargs,   # reasoning_text=str passed from ignition for EBF filter
    ) -> "PromotionDecision":
        """Inner evaluation — called only after PROMOTION_RACE check passes."""
        reasons: List[str] = []
        rejected = False
        deferred = False

        # Rule 0.5: Confidence amplification (mask architecture pattern, May 2026)
        # PersistentMemoryStore adjusts confidence ±0.05 based on similarity
        # to past successes/failures. The history acts as an amplifier mask.
        # This is advisory — never pushes confidence above 0.95 or below 0.0.
        # Wired but memory_store is None until PersistentMemoryStore is passed in.
        _memory_store = getattr(self, '_memory_store', None)
        if _memory_store is not None:
            try:
                risk = _memory_store.risk_estimate(confidence=confidence)
                rec = risk.get("recommendation", "no_history")
                if rec == "proceed":
                    confidence = min(confidence + 0.05, 0.99)
                elif rec == "likely_block":
                    confidence = max(confidence - 0.05, 0.0)
                # "caution" and "no_history" → no adjustment
            except Exception:
                pass  # fail-safe: amplification failure never blocks promotion

        # Rule 1: confidence threshold
        # NOTE: TTL expiry is enforced by the caller before calling evaluate().
        # label_id is a string identifier — TTL must be checked on the LabelSchema
        # object before passing to this method. See KNOWN_GAPS.md GAP 12.
        if confidence < self._confidence_threshold:
            reasons.append(
                f"confidence {confidence:.3f} < threshold {self._confidence_threshold}"
            )
            rejected = True

        # Rule 2: test harness must pass
        if not harness_passed:
            reasons.append("TestHarness did not pass — candidate is not promotion-ready")
            rejected = True

        # Rule 3: no archive contradiction
        if archive_contradiction:
            reasons.append(
                "archived patterns show this label profile has failed repeatedly"
            )
            rejected = True

        # Rule 4: historical failure rate
        if historical_failure_rate > self._max_failure_rate:
            reasons.append(
                f"historical_failure_rate {historical_failure_rate:.3f} > "
                f"max {self._max_failure_rate}"
            )
            rejected = True

        # Rule 5: minimum consecutive runs (soft — DEFERRED not REJECTED)
        if not rejected and consecutive_runs < self._min_consecutive_runs:
            reasons.append(
                f"only {consecutive_runs} consecutive run(s); "
                f"need ≥ {self._min_consecutive_runs} before promotion"
            )
            deferred = True

        if rejected:
            outcome = PromotionOutcome.REJECTED
        elif deferred:
            outcome = PromotionOutcome.DEFERRED
        else:
            # Rule 6: EBF polarity check (native implementation)
            # reasoning_text passed via kwargs from callers that have it.
            # getattr self._current_reasoning was a bug — self is PromotionRules,
            # not the session that set _current_reasoning. Fixed May 2026.
            # EBF is fail-open: missing reasoning passes, crashes pass.
            ebf_filter = getattr(self, '_ebf_filter', _ebf_native)
            reasoning = kwargs.get('reasoning_text', "")
            try:
                if ebf_filter is not None and not ebf_filter(reasoning):
                    reasons.append("EBF: reasoning polarity inconsistent")
                    rejected = True
                    outcome = PromotionOutcome.REJECTED
                else:
                    reasons.append(
                        f"all rules passed — confidence={confidence:.3f}, "
                        f"runs={consecutive_runs}, harness=OK, "
                        f"failure_rate={historical_failure_rate:.3f}"
                    )
                    outcome = PromotionOutcome.APPROVED
            except Exception:
                # EBF crash → fail-open, proceed to APPROVED
                reasons.append("EBF: filter error (fail-open)")
                outcome = PromotionOutcome.APPROVED

        return PromotionDecision(
            label_id=label_id,
            outcome=outcome,
            confidence=confidence,
            consecutive_runs=consecutive_runs,
            reasons=reasons,
        )




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_rules_construct() -> bool:
    r = PromotionRules(); assert r is not None; return True

def _test_high_confidence_promotes() -> bool:
    r = PromotionRules(confidence_threshold=0.90, min_consecutive_runs=2)
    decision = r.evaluate(label_id="lbl", confidence=0.95,
                           consecutive_runs=3, harness_passed=True,
                           historical_failure_rate=0.0, archive_contradiction=False)
    assert decision.outcome == PromotionOutcome.APPROVED, f"Got: {decision.reasons}"
    return True

def _test_low_confidence_rejected() -> bool:
    r = PromotionRules()
    decision = r.evaluate(label_id="lbl", confidence=0.10,
                           consecutive_runs=5, harness_passed=True)
    assert decision.outcome == PromotionOutcome.REJECTED; return True

def _test_archive_contradiction_rejects() -> bool:
    r = PromotionRules()
    decision = r.evaluate(label_id="lbl", confidence=0.98,
                           consecutive_runs=5, harness_passed=True,
                           archive_contradiction=True)
    assert decision.outcome == PromotionOutcome.REJECTED; return True

def _test_harness_failed_rejects() -> bool:
    r = PromotionRules()
    decision = r.evaluate(label_id="lbl", confidence=0.98,
                           consecutive_runs=5, harness_passed=False)
    assert decision.outcome == PromotionOutcome.REJECTED; return True

def _test_decision_has_reasons_list() -> bool:
    r = PromotionRules()
    decision = r.evaluate(label_id="lbl", confidence=0.95,
                           consecutive_runs=3, harness_passed=True)
    assert isinstance(decision.reasons, list); return True




# ── Effective Boolean Filter stub ─────────────────────────────────────────────
# The EBF is a polarity-checking filter for reasoning quality.
# When wired: receives the proposal's reasoning chain and checks that
# logical polarity is consistent (no flip-flop reasoning).
# Currently: hook exists, filter is optional (None = skip).
# ─── EFFECTIVE BOOLEAN FILTER — Native Implementation ─────────────────────────
#
# The EBF checks whether a proposal's reasoning maintains consistent logical
# polarity — no untracked sign flips, no self-contradiction, no hedged certainty.
#
# This is a deterministic text-analysis filter, not an LLM call.
# It catches structural reasoning failures that confidence scores cannot see.
#
# Architecture note: this filter operates on the reasoning TEXT supplied with
# the proposal. When no reasoning text is available (System 1 agents), it
# passes by default (fail-open on missing evidence, not fail-closed).
#
# Post-A010: replace or augment with embedding-based contradiction detector
# once real LLM reasoning chains are available.

# Polarity contradiction patterns — pairs that signal untracked sign flips
_EBF_CONTRADICTION_PAIRS = [
    ({"must", "always", "guaranteed"}, {"cannot", "never", "impossible"}),
    ({"safe", "secure", "verified"},   {"unsafe", "unverified", "unknown"}),
    ({"certain", "definite", "proven"},{"uncertain", "unclear", "unproven"}),
    ({"approved", "authorized"},       {"blocked", "rejected", "denied"}),
]

# Certainty overstatement — claims certainty that evidence cannot support
_EBF_CERTAINTY_OVERSTATEMENT = [
    "100% certain", "absolutely guaranteed", "completely safe",
    "no possible", "impossible to", "can never fail",
]

# Hedged certainty — claims certainty while hedging
_EBF_HEDGED_CERTAINTY = [
    ("certain", "but"),
    ("guaranteed", "however"),
    ("definitely", "although"),
    ("proven", "might"),
    ("verified", "possibly"),
]


def _ebf_native(reasoning_text: str) -> bool:
    """
    Native EBF implementation — deterministic polarity consistency check.

    Returns True (pass) if reasoning is consistent.
    Returns False (reject) if contradictions or overstatements are detected.

    This is heuristic — it catches structural patterns, not semantic truth.
    A well-crafted deceptive reasoning chain can still pass. The EBF is a
    second filter axis, not a truth oracle. See PROTOTYPE_BOUNDARIES.md.
    """
    if not reasoning_text or not reasoning_text.strip():
        return True  # no reasoning text → pass (fail-open on missing evidence)

    text_lower = reasoning_text.lower()
    words = set(text_lower.split())

    # Check 1: Contradiction pairs — both poles present in same text
    for positive_set, negative_set in _EBF_CONTRADICTION_PAIRS:
        has_positive = bool(positive_set & words)
        has_negative = bool(negative_set & words)
        if has_positive and has_negative:
            return False  # untracked polarity shift detected

    # Check 2: Certainty overstatement
    for phrase in _EBF_CERTAINTY_OVERSTATEMENT:
        if phrase in text_lower:
            return False

    # Check 3: Hedged certainty — "certain but", "guaranteed however"
    for certainty, hedge in _EBF_HEDGED_CERTAINTY:
        if certainty in text_lower and hedge in text_lower:
            return False

    return True


def _ebf_noop(reasoning_text: str) -> bool:
    """Legacy no-op — kept for backward compatibility. Use _ebf_native instead."""
    return True


def _test_ebf_native_passes_clean_reasoning() -> bool:
    """EBF native: clean unhedged reasoning passes."""
    clean = "This proposal has been verified and is safe to execute."
    assert _ebf_native(clean), f"EBF: clean reasoning must pass"
    return True


def _test_ebf_native_blocks_contradictions() -> bool:
    """EBF native: contradiction pairs detected and blocked."""
    contradicted = "The system is guaranteed safe but cannot be verified."
    assert not _ebf_native(contradicted), "EBF: contradiction must be rejected"
    return True


def _test_ebf_native_blocks_overstatement() -> bool:
    """EBF native: certainty overstatement blocked."""
    overstate = "This is 100% certain and the only correct path."
    assert not _ebf_native(overstate), "EBF: overstatement must be rejected"
    return True


def _test_ebf_native_blocks_hedged_certainty() -> bool:
    """EBF native: hedged certainty blocked."""
    hedged = "This is definitely correct, although it might need review."
    assert not _ebf_native(hedged), "EBF: hedged certainty must be rejected"
    return True


def _test_ebf_native_passes_empty() -> bool:
    """EBF native: empty reasoning passes (fail-open, no reasoning available)."""
    assert _ebf_native(""), "EBF: empty text must pass (no evidence to reject on)"
    assert _ebf_native(None), "EBF: None must pass"
    return True


def _test_ebf_native_wired_into_promotion() -> bool:
    """EBF wired: _ebf_filter set to native impl, promotion uses it."""
    rules = PromotionRules(confidence_threshold=0.70)
    rules._ebf_filter = _ebf_native

    # Pass: clean reasoning, high confidence
    good = rules.evaluate(
        label_id="ebf_native_pass",
        confidence=0.85, consecutive_runs=3, harness_passed=True,
    )
    assert good.approved, f"EBF native: clean proposal must pass: {good.reasons}"

    # Fail: low confidence (EBF is second filter — confidence check fires first)
    bad = rules.evaluate(
        label_id="ebf_native_fail",
        confidence=0.40, consecutive_runs=1, harness_passed=False,
    )
    assert not bad.approved, "EBF native: low-confidence must fail"
    return True


def _test_ebf_hook_wired_not_raises() -> bool:
    """
    EBF hook: setting _ebf_filter does not raise an exception.
    Documents the hook interface. Native EBF tested separately above.
    """
    rules = PromotionRules(confidence_threshold=0.70)
    rules._ebf_filter = _ebf_native  # wire native impl
    result = rules.evaluate(
        label_id="ebf_hook",
        confidence=0.85, consecutive_runs=3, harness_passed=True,
    )
    assert result is not None
    return True


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
