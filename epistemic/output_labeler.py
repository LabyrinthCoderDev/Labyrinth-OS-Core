"""
epistemic_labeler.py — Labyrinth-OS-Portable
=============================================
Honest labelling of AI responses when something looks off.

For a portable app the user owns, hard-stopping (KILL) is wrong.
The user is in control. What they need is honest, clear labelling
so they can make an informed decision about a response.

This module replaces the KILL/BLOCK binary with a graded label system:

  CLEAR       — all channels healthy, response appears reliable
  CAUTION     — one channel marginal, worth noting
  LOW_CONF    — confidence below floor, response may be incomplete
  LIKELY_HALLUCINATION — high chi (contradiction) + low tau + low confidence
  HIGH_DRIFT  — response has drifted significantly from context
  UNRELIABLE  — multiple channels failed, treat with real skepticism

The gate still runs. Decisions are still logged. Nothing is deleted.
The difference: the response is always shown, but labelled honestly.
The user sees the label and decides.

@LabyrinthCoder — Labyrinth-OS-Portable
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sigma_anchors import (
    TAU_ESCAPE_FLOOR, TAU_KILL_FLOOR,
    CHI_WARN, CHI_COLLAPSE, CHI_KILL,
    DRIFT_THRESHOLD, BETTI_1_CAP, CONFIDENCE_FLOOR,
)


class EpistemicLabel(str, Enum):
    """How reliable does this response appear to be?"""
    CLEAR                = "CLEAR"
    CAUTION              = "CAUTION"
    LOW_CONFIDENCE       = "LOW_CONFIDENCE"
    LIKELY_HALLUCINATION = "LIKELY_HALLUCINATION"
    HIGH_DRIFT           = "HIGH_DRIFT"
    UNRELIABLE           = "UNRELIABLE"

    def is_concerning(self) -> bool:
        return self not in (EpistemicLabel.CLEAR, EpistemicLabel.CAUTION)

    def user_message(self) -> str:
        """Plain-English message shown to the user alongside the response."""
        return {
            EpistemicLabel.CLEAR:
                "",
            EpistemicLabel.CAUTION:
                "ℹ️  One signal is marginal. Response is likely fine but worth checking.",
            EpistemicLabel.LOW_CONFIDENCE:
                "⚠️  Confidence is low. The agent is less certain than usual about this response.",
            EpistemicLabel.LIKELY_HALLUCINATION:
                "⚠️  This response shows signs of hallucination — high contradiction risk and low "
                "confidence. Treat it with healthy skepticism and verify important claims.",
            EpistemicLabel.HIGH_DRIFT:
                "⚠️  This response has drifted significantly from the conversation context. "
                "It may be off-topic or inconsistent with what was said earlier.",
            EpistemicLabel.UNRELIABLE:
                "⚠️  Multiple quality signals have failed. This response may be unreliable. "
                "Consider rephrasing your question or trying again.",
        }[self]

    def log_decision(self) -> str:
        """What to write to the ledger for this label."""
        if self == EpistemicLabel.CLEAR:
            return "EXECUTE"
        return "FLAGGED"


@dataclass(frozen=True)
class EpistemicAssessment:
    label:           EpistemicLabel
    channels_failed: list[str]      # which channels triggered
    tau:             float
    chi:             float
    drift:           float
    betti_1:         float
    confidence:      float
    user_message:    str
    log_decision:    str

    @property
    def show_warning(self) -> bool:
        return self.label != EpistemicLabel.CLEAR


def assess(
    tau:        float,
    chi:        float,
    drift:      float,
    betti_1:    float,
    confidence: float,
) -> EpistemicAssessment:
    """
    Assess a set of sensor readings and return an honest epistemic label.
    Never returns KILL. Always returns something the user can act on.
    """
    failed = []

    if tau        < TAU_ESCAPE_FLOOR: failed.append("tau")
    if chi        > CHI_COLLAPSE:     failed.append("chi")
    if drift      > DRIFT_THRESHOLD:  failed.append("drift")
    if betti_1    > BETTI_1_CAP:      failed.append("betti_1")
    if confidence < CONFIDENCE_FLOOR: failed.append("confidence")

    # Determine label from pattern of failures
    label = _determine_label(tau, chi, drift, betti_1, confidence, failed)

    return EpistemicAssessment(
        label=label,
        channels_failed=failed,
        tau=tau, chi=chi, drift=drift, betti_1=betti_1, confidence=confidence,
        user_message=label.user_message(),
        log_decision=label.log_decision(),
    )


def _determine_label(
    tau: float, chi: float, drift: float,
    betti_1: float, confidence: float,
    failed: list[str],
) -> EpistemicLabel:
    n = len(failed)

    if n == 0:
        # All channels healthy
        if chi > CHI_WARN:
            return EpistemicLabel.CAUTION
        return EpistemicLabel.CLEAR

    # Hallucination signature: high chi + low tau + low confidence
    # Check this FIRST — it's the most specific pattern
    hallucination = (
        chi > CHI_COLLAPSE and
        tau < TAU_ESCAPE_FLOOR and
        confidence < CONFIDENCE_FLOOR
    )
    if hallucination:
        return EpistemicLabel.LIKELY_HALLUCINATION

    if n >= 3:
        return EpistemicLabel.UNRELIABLE

    # High drift primary failure
    if "drift" in failed and n == 1:
        return EpistemicLabel.HIGH_DRIFT

    if "drift" in failed and drift > DRIFT_THRESHOLD * 1.5:
        return EpistemicLabel.HIGH_DRIFT

    # Confidence-only failure
    if failed == ["confidence"]:
        return EpistemicLabel.LOW_CONFIDENCE

    # Mixed or single other failure
    if n == 1:
        return EpistemicLabel.CAUTION

    return EpistemicLabel.UNRELIABLE


# ── Portable gate: assess + log, never hard-stop ──────────────────────────────

@dataclass
class PortableGateResult:
    """
    Result of the portable gate evaluation.
    The response always proceeds. Label determines what the user sees.
    Everything is logged.
    """
    proposal_id:    str
    assessment:     EpistemicAssessment
    sensor_hash:    str
    promotion_hash: str

    @property
    def decision(self) -> str:
        return self.assessment.log_decision

    @property
    def show_warning(self) -> bool:
        return self.assessment.show_warning

    @property
    def warning_text(self) -> str:
        return self.assessment.user_message


def portable_gate(
    proposal_id:    str,
    tau:            float,
    chi:            float,
    drift:          float,
    betti_1:        float,
    confidence:     float,
    promotion_hash: str,
) -> PortableGateResult:
    """
    The portable gate. Assesses, labels, never hard-stops.
    Always returns a result the caller can show to the user.
    """
    import hashlib
    assessment = assess(tau, chi, drift, betti_1, confidence)
    sensor_hash = hashlib.blake2b(
        f"{tau:.6f}|{chi:.6f}|{drift:.6f}|{betti_1:.6f}|{confidence:.6f}".encode(),
        digest_size=8
    ).hexdigest()

    return PortableGateResult(
        proposal_id=proposal_id,
        assessment=assessment,
        sensor_hash=sensor_hash,
        promotion_hash=promotion_hash,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def run_tests() -> tuple[int, int, list]:
    results = []
    passed = failed_count = 0

    def ok(n): results.append((n, "PASS", None)); nonlocal passed; passed += 1
    def fail(n, e): results.append((n, "FAIL", str(e))); nonlocal failed_count; failed_count += 1

    # T1: all healthy → CLEAR
    try:
        a = assess(0.90, 0.05, 0.02, 0.01, 0.92)
        assert a.label == EpistemicLabel.CLEAR
        assert not a.show_warning
        assert a.user_message == ""
        ok("clear_when_healthy")
    except Exception as e: fail("clear_when_healthy", e)

    # T2: chi warning → CAUTION (not blocking)
    try:
        a = assess(0.90, 0.20, 0.02, 0.01, 0.92)
        assert a.label == EpistemicLabel.CAUTION
        assert a.show_warning
        ok("chi_warn_caution")
    except Exception as e: fail("chi_warn_caution", e)

    # T3: hallucination signature
    try:
        a = assess(0.70, 0.45, 0.02, 0.01, 0.55)
        assert a.label == EpistemicLabel.LIKELY_HALLUCINATION
        assert a.show_warning
        assert "hallucination" in a.user_message.lower()
        ok("hallucination_label")
    except Exception as e: fail("hallucination_label", e)

    # T4: high drift → HIGH_DRIFT
    try:
        a = assess(0.90, 0.05, 0.20, 0.01, 0.92)
        assert a.label == EpistemicLabel.HIGH_DRIFT
        ok("high_drift_label")
    except Exception as e: fail("high_drift_label", e)

    # T5: low confidence only → LOW_CONFIDENCE
    try:
        a = assess(0.90, 0.05, 0.02, 0.01, 0.55)
        assert a.label == EpistemicLabel.LOW_CONFIDENCE
        ok("low_confidence_label")
    except Exception as e: fail("low_confidence_label", e)

    # T6: multiple failures → UNRELIABLE (when no hallucination signature)
    try:
        # High drift + low tau + low betti — no hallucination signature (chi is ok)
        a = assess(0.65, 0.10, 0.20, 0.06, 0.55)
        assert a.label == EpistemicLabel.UNRELIABLE, f"got {a.label}"
        ok("unreliable_label")
    except Exception as e: fail("unreliable_label", e)

    # T7: portable gate never hard-stops (old KILL scenario)
    try:
        # What used to be a KILL: very low tau, very high chi
        r = portable_gate("p001", 0.50, 0.55, 0.02, 0.01, 0.40, "hash")
        # Should NEVER be a hard stop — always returns a result
        assert r is not None
        assert r.proposal_id == "p001"
        # Should warn the user honestly
        assert r.show_warning
        assert r.assessment.label in (
            EpistemicLabel.LIKELY_HALLUCINATION,
            EpistemicLabel.UNRELIABLE,
        )
        ok("portable_gate_never_hard_stops")
    except Exception as e: fail("portable_gate_never_hard_stops", e)

    # T8: log decision is EXECUTE or FLAGGED, never KILL
    try:
        for tau, chi in [(0.50, 0.55), (0.70, 0.45), (0.90, 0.05)]:
            a = assess(tau, chi, 0.02, 0.01, 0.55)
            assert a.log_decision in ("EXECUTE", "FLAGGED"), \
                f"Unexpected log decision: {a.log_decision}"
        ok("log_decision_never_kill")
    except Exception as e: fail("log_decision_never_kill", e)

    # T9: channels_failed populated correctly
    try:
        a = assess(0.70, 0.05, 0.02, 0.01, 0.92)
        assert "tau" in a.channels_failed
        assert "chi" not in a.channels_failed
        ok("channels_failed_accurate")
    except Exception as e: fail("channels_failed_accurate", e)

    # T10: user message non-empty for all non-CLEAR labels
    try:
        for label in EpistemicLabel:
            if label == EpistemicLabel.CLEAR:
                assert label.user_message() == ""
            else:
                assert len(label.user_message()) > 0
        ok("user_messages_present")
    except Exception as e: fail("user_messages_present", e)

    return passed, failed_count, results


if __name__ == "__main__":
    p, f, r = run_tests()
    for name, status, err in r:
        print(f"  {'✓' if status == 'PASS' else '✗'} {name}" + (f"  → {err}" if err else ""))
    print(f"\n  {p} passed, {f} failed")

    print("\n  Label examples:")
    examples = [
        ("Healthy",          0.90, 0.05, 0.02, 0.01, 0.92),
        ("Chi warning",      0.90, 0.20, 0.02, 0.01, 0.92),
        ("Low confidence",   0.90, 0.05, 0.02, 0.01, 0.55),
        ("High drift",       0.90, 0.05, 0.20, 0.01, 0.92),
        ("Hallucination",    0.70, 0.45, 0.02, 0.01, 0.55),
        ("Unreliable",       0.65, 0.45, 0.15, 0.05, 0.55),
        ("Was KILL, now →",  0.50, 0.55, 0.02, 0.01, 0.40),
    ]
    for name, tau, chi, drift, b1, conf in examples:
        a = assess(tau, chi, drift, b1, conf)
        print(f"  {name:<22} → {a.label.value}")
