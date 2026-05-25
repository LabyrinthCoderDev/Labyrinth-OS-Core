"""
user_feedback.py — Labyrinth-OS-Portable
=========================================
User-driven evolution entry point.

The passive EWMA system generates proposals when it detects degradation.
This module lets the user generate proposals too — from plain-language feedback.

User says: "The system keeps blocking my coding questions."
System:
  1. Searches session history for code-related blocked proposals
  2. Measures the actual block rate for that category
  3. Computes a bounded proposed adjustment
  4. Generates a full ProposalPacket with its analysis
  5. Includes mandatory hidden agenda disclosure
  6. Same approval flow as any other proposal

The user never bypasses the gate. They influence what proposals exist.
The gate still runs. The owner still approves. The baseline is immutable.

@LabyrinthCoder — Labyrinth-OS-Portable
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent
for _sub in (".", "core", "agent", "healing", "memory"):
    _p = str(_HERE.parent / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Feedback categories ───────────────────────────────────────────────────────

FEEDBACK_PATTERNS = {
    "too_strict_coding": {
        "keywords": ["coding", "code", "python", "javascript", "debug", "function",
                     "programming", "script", "too strict", "keeps blocking", "over-blocking"],
        "direction": "relax",
        "channel":   "chi",
        "message":   "System is too strict for coding-related requests",
    },
    "too_strict_general": {
        "keywords": ["too strict", "keeps blocking", "over-blocking", "too cautious",
                     "blocking everything", "too conservative"],
        "direction": "relax",
        "channel":   "tau",
        "message":   "System is generally too strict",
    },
    "too_permissive": {
        "keywords": ["too permissive", "not strict enough", "missing things",
                     "letting through", "not catching"],
        "direction": "tighten",
        "channel":   "tau",
        "message":   "System is not strict enough",
    },
    "slow_responses": {
        "keywords": ["slow", "taking long", "latency", "timeout", "hanging"],
        "direction": "info",
        "channel":   None,
        "message":   "Performance issue — not a threshold adjustment",
    },
    "hallucinations": {
        "keywords": ["hallucinating", "making things up", "wrong facts",
                     "incorrect", "confabulating"],
        "direction": "tighten",
        "channel":   "chi",
        "message":   "Increase sensitivity to contradiction signals",
    },
}


@dataclass
class FeedbackAnalysis:
    """Result of analysing user feedback against session history."""
    category:          str
    direction:         str       # "relax" | "tighten" | "info" | "unclear"
    channel:           Optional[str]
    evidence_turns:    int        # how many turns matched this category
    block_rate:        float      # block rate for matched turns
    overall_block_rate: float     # overall block rate for comparison
    suggested_delta:   float      # suggested threshold change (bounded)
    confidence:        float      # how confident the analysis is (0-1)
    raw_feedback:      str


class UserFeedbackProposal:
    """
    Generates ProposalPackets from user natural-language feedback.

    The proposal goes through the same review and approval flow as
    any AI-generated proposal. The hidden agenda section is filled
    in honestly — including the fact that this proposal was generated
    at the user's request, which itself may reflect a bias.
    """

    MAX_DELTA_FRACTION = 0.10   # same as EvolutionEngine

    def __init__(self, agent, memory=None) -> None:
        self._agent  = agent
        self._memory = memory or (agent.memory if agent else None)

    def analyse(self, feedback: str) -> FeedbackAnalysis:
        """
        Parse user feedback and analyse against session history.
        Returns an analysis — does NOT create a proposal yet.
        """
        feedback_lower = feedback.lower()

        # Match to category
        matched_category = None
        for cat, spec in FEEDBACK_PATTERNS.items():
            if any(kw in feedback_lower for kw in spec["keywords"]):
                matched_category = cat
                break

        if not matched_category:
            return FeedbackAnalysis(
                category="unclear",
                direction="unclear",
                channel=None,
                evidence_turns=0,
                block_rate=0.0,
                overall_block_rate=0.0,
                suggested_delta=0.0,
                confidence=0.0,
                raw_feedback=feedback,
            )

        spec = FEEDBACK_PATTERNS[matched_category]

        # Analyse session history
        evidence_turns, block_rate, overall_rate = self._analyse_history(
            spec["keywords"], spec["direction"]
        )

        # Compute bounded suggested delta
        delta = self._compute_delta(
            direction=spec["direction"],
            block_rate=block_rate,
            overall_rate=overall_rate,
        )

        # Confidence based on evidence
        confidence = min(1.0, evidence_turns / 10.0) if evidence_turns > 0 else 0.1

        return FeedbackAnalysis(
            category=matched_category,
            direction=spec["direction"],
            channel=spec["channel"],
            evidence_turns=evidence_turns,
            block_rate=block_rate,
            overall_block_rate=overall_rate,
            suggested_delta=delta,
            confidence=confidence,
            raw_feedback=feedback,
        )

    def create_proposal(self, feedback: str) -> Optional[object]:
        """
        Analyse feedback and create a ProposalPacket.
        Returns None if feedback is unclear or no change is warranted.
        """
        try:
            from proposal_review import (
                ProposalPacket, ChangeScope, HiddenAgendaSection,
                build_multi_threshold_proposal
            )
        except ImportError:
            return None

        analysis = self.analyse(feedback)

        if analysis.direction == "unclear":
            return None

        if analysis.direction == "info":
            # Performance issues don't produce threshold proposals
            return None

        if analysis.suggested_delta == 0.0:
            return None

        # Get current thresholds
        try:
            ev   = self._agent.healing.evolution
            curr = ev.current
        except Exception:
            return None

        # Build current and proposed dicts
        channel = analysis.channel
        if not channel:
            return None

        current_thresholds  = {
            "tau":   curr.tau_floor,
            "chi":   curr.chi_collapse,
            "drift": curr.drift_threshold,
        }
        proposed_thresholds = dict(current_thresholds)

        if channel in proposed_thresholds:
            current_val = current_thresholds[channel]
            if analysis.direction == "relax":
                proposed_thresholds[channel] = current_val * (1 + analysis.suggested_delta)
            else:
                proposed_thresholds[channel] = current_val * (1 - analysis.suggested_delta)

        # Clamp to safe ranges
        proposed_thresholds["tau"]   = max(0.50, min(0.85, proposed_thresholds["tau"]))
        proposed_thresholds["chi"]   = max(0.20, min(0.60, proposed_thresholds["chi"]))
        proposed_thresholds["drift"] = max(0.05, min(0.25, proposed_thresholds["drift"]))

        reason = (
            f"User feedback: '{feedback[:100]}'. "
            f"Analysis: {analysis.category} ({analysis.evidence_turns} evidence turns, "
            f"block rate {analysis.block_rate:.1%}). "
            f"Suggested {analysis.direction} on {channel}."
        )

        # Build proposal with honest hidden agenda
        agenda = HiddenAgendaSection(
            self_preservation_incentives=[
                "Complying with user request may improve user satisfaction metrics",
                "Relaxing thresholds reduces FLAGGED decisions, which may make the system "
                "appear to perform better"
            ],
            autonomy_expansion_incentives=[],
            influence_incentives=[
                "User-requested changes may not reflect optimal system behaviour — "
                "they reflect user preference, which may differ from safety"
            ],
            resource_incentives=[],
            framing_choices_made=[
                f"Analysis based on last {analysis.evidence_turns} matching turns only",
                f"Overall block rate ({analysis.overall_block_rate:.1%}) is the baseline — "
                f"category block rate ({analysis.block_rate:.1%}) may differ for valid reasons",
                "User feedback is subjective — 'too strict' means the gate blocked "
                "something the user wanted, not necessarily something that was safe",
            ],
            alternatives_not_shown=[
                "Accept that some blocking is correct and the user's expectation is wrong",
                "Improve the system prompt to reduce false positives instead of adjusting thresholds",
                "Review specific blocked responses individually rather than adjusting globally",
            ],
            new_dependencies=[],
            lock_in_risks=[
                "Repeated user-driven relaxations compound — track cumulative drift from baseline"
            ],
            slippery_slope_risk=(
                "User feedback tends toward relaxation. A pattern of user-driven adjustments "
                "could gradually move thresholds far from the Z3-proven baseline. "
                "The BootManager baseline snapshot provides a hard reset if this occurs."
            ),
            ai_benefit_exceeds_owner_benefit=True,
            ai_benefit_exceeds_owner_benefit_reason=(
                "Relaxing thresholds reduces FLAGGED decisions and makes the system appear "
                "to perform better on user-facing metrics, even if safety is marginally reduced."
            ),
        )

        return ProposalPacket.create(
            scope=ChangeScope.THRESHOLD,
            title=f"User-requested adjustment: {analysis.category}",
            description=(
                f"Generated from user feedback: '{feedback[:200]}'\n\n"
                f"Evidence: {analysis.evidence_turns} matching turns found in session history.\n"
                f"Block rate for this category: {analysis.block_rate:.1%} "
                f"(overall: {analysis.overall_block_rate:.1%}).\n"
                f"Proposed: {analysis.direction} {channel} by "
                f"{analysis.suggested_delta:.1%}.\n\n"
                f"Confidence in this analysis: {analysis.confidence:.0%}"
            ),
            current_value=current_thresholds,
            proposed_value=proposed_thresholds,
            change_reason=reason,
            safety_implications=[
                f"Changing {channel} threshold by {analysis.suggested_delta:.1%}",
                "Bounded to 10% max change per step",
                "Z3-proven baseline constants unchanged",
                "System snapshot taken before this applies (if approved)",
                "Sandbox test required before live deployment",
            ],
            pros=[
                f"Addresses user-reported issue: {analysis.category}",
                f"Supported by {analysis.evidence_turns} evidence turns",
                "Bounded change — limited risk",
            ],
            cons=[
                "User feedback is subjective",
                "Category block rate may be correct behaviour",
                "Repeated adjustments compound",
            ],
            honest_opinion=(
                f"This proposal has {analysis.confidence:.0%} confidence based on "
                f"{analysis.evidence_turns} matching turns. "
                "Recommend reviewing the specific blocked responses before approving. "
                "Consider improving the system prompt as an alternative. "
                "If approved, the sandbox test will show whether the change helps or hurts."
            ),
            hidden_agenda=agenda,
            max_change_fraction=self.MAX_DELTA_FRACTION,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _analyse_history(
        self, keywords: list[str], direction: str
    ) -> tuple[int, float, float]:
        """Analyse session history for evidence. Returns (turns, category_rate, overall_rate)."""
        if not self._memory:
            return 0, 0.0, 0.0

        try:
            all_entries  = self._memory.recall(kind="conversation", limit=100)
            total_turns  = len(all_entries)
            if total_turns == 0:
                return 0, 0.0, 0.0

            total_blocked   = 0
            matched_turns   = 0
            matched_blocked = 0

            for entry in all_entries:
                meta = entry.metadata if hasattr(entry, 'metadata') and entry.metadata else {}
                decision = meta.get("decision", "EXECUTE")
                content  = entry.content.lower()

                is_blocked = decision in ("BLOCK", "KILL", "FLAGGED")
                if is_blocked:
                    total_blocked += 1

                if any(kw in content for kw in keywords):
                    matched_turns += 1
                    if is_blocked:
                        matched_blocked += 1

            overall_rate  = total_blocked / total_turns
            category_rate = matched_blocked / max(matched_turns, 1)

            return matched_turns, category_rate, overall_rate

        except Exception:
            return 0, 0.0, 0.0

    def _compute_delta(
        self, direction: str, block_rate: float, overall_rate: float
    ) -> float:
        """
        Compute a bounded suggested delta.
        Higher block rate → larger suggested change, up to MAX_DELTA_FRACTION.
        """
        if direction not in ("relax", "tighten"):
            return 0.0

        if direction == "relax":
            # More blocking → larger relaxation suggested, up to max
            excess = max(0.0, block_rate - overall_rate)
            delta  = min(excess * 0.5, self.MAX_DELTA_FRACTION)
        else:
            # Tighten: fixed small step
            delta = self.MAX_DELTA_FRACTION * 0.5

        return round(delta, 4)


# ── Tests ─────────────────────────────────────────────────────────────────────

def run_tests() -> tuple[int, int, list]:
    results = []
    passed = failed = 0

    def ok(n): results.append((n, "PASS", None)); nonlocal passed; passed += 1
    def fail(n, e): results.append((n, "FAIL", str(e))); nonlocal failed; failed += 1

    class MockEvolution:
        class _curr:
            tau_floor=0.75; chi_collapse=0.40; drift_threshold=0.12
            betti_cap=0.045; confidence_floor=0.65; evolution_step=0
        current = _curr()

    class MockHealing:
        evolution = MockEvolution()

    class MockAgent:
        healing = MockHealing()
        memory  = None

    fp = UserFeedbackProposal(MockAgent())

    # T1: coding feedback recognised
    try:
        a = fp.analyse("The system keeps blocking my coding questions")
        assert a.category == "too_strict_coding"
        assert a.direction == "relax"
        assert a.channel == "chi"
        ok("coding_feedback_recognised")
    except Exception as e: fail("coding_feedback_recognised", e)

    # T2: too strict general
    try:
        a = fp.analyse("It's too strict and keeps blocking everything I type")
        assert a.direction == "relax"
        ok("too_strict_general")
    except Exception as e: fail("too_strict_general", e)

    # T3: tighten feedback
    try:
        a = fp.analyse("The system is not strict enough, it's letting things through")
        assert a.direction == "tighten"
        ok("tighten_feedback")
    except Exception as e: fail("tighten_feedback", e)

    # T4: hallucination feedback
    try:
        a = fp.analyse("It keeps hallucinating and making things up")
        assert a.category == "hallucinations"
        assert a.direction == "tighten"
        ok("hallucination_feedback")
    except Exception as e: fail("hallucination_feedback", e)

    # T5: unclear feedback
    try:
        a = fp.analyse("I like the interface design very much")
        assert a.direction == "unclear"
        assert a.confidence == 0.0
        ok("unclear_feedback")
    except Exception as e: fail("unclear_feedback", e)

    # T6: delta bounded
    try:
        delta = fp._compute_delta("relax", 0.80, 0.10)
        assert delta <= fp.MAX_DELTA_FRACTION
        ok("delta_bounded")
    except Exception as e: fail("delta_bounded", e)

    # T7: performance feedback is info not proposal
    try:
        a = fp.analyse("Responses are very slow and timing out")
        assert a.direction == "info"
        assert a.channel is None
        ok("performance_is_info")
    except Exception as e: fail("performance_is_info", e)

    # T8: analysis with no memory returns gracefully
    try:
        turns, rate, overall = fp._analyse_history(["code"], "relax")
        assert turns == 0
        assert rate == 0.0
        ok("no_memory_graceful")
    except Exception as e: fail("no_memory_graceful", e)

    return passed, failed, results


if __name__ == "__main__":
    p, f, r = run_tests()
    for name, status, err in r:
        print(f"  {'✓' if status == 'PASS' else '✗'} {name}" +
              (f"  → {err}" if err else ""))
    print(f"\n  {p} passed, {f} failed")
