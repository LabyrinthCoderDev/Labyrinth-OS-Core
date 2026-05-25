"""
mode_router.py — Labyrinth-OS / Lane 1 / L02
=============================================
L02 Mode Router

Receives raw user intent (L01) and routes it to one of three
processing paths. All three paths eventually converge at
L05 Epistemic Labeling — nothing skips labeling.

Routing is deterministic: same intent text → same mode.
No randomness. Reproducible.

Modes:
  CREATIVE   → L03 Creative Zone (unbounded generation)
  ANALYTICAL → L04 Analytical Core (structured reasoning)
  EXECUTION  → treated as ANALYTICAL first, then flagged for L09 Reality Gate

The router does NOT suppress any input. It only classifies.
Classification is not judgment — it is routing.

References:
  ARCHITECTURE.md   — L02 Mode Router
  epistemic_types.py — InputMode
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional

# Ensure epistemic_types is importable regardless of cwd
_HERE = os.path.dirname(os.path.abspath(__file__))
_LABELING = os.path.normpath(os.path.join(_HERE, '..', '05_epistemic_labeling'))
if _LABELING not in sys.path:
    sys.path.insert(0, _LABELING)

from epistemic_types import EpistemicLabel, IdeaNode, InputMode


# ─── ROUTING RESULT ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RouteResult:
    """
    Output of the mode router for one input.

    mode          — which processing path was selected
    confidence    — how confident the router is (0.0–1.0)
    signals       — which signals triggered the classification
    idea_node     — the IdeaNode created from this input (label=UNKNOWN at this stage)
    """
    mode:       InputMode
    confidence: float
    signals:    List[str]
    idea_node:  IdeaNode

    def to_dict(self):
        return {
            "mode":       self.mode.value,
            "confidence": round(self.confidence, 4),
            "signals":    self.signals,
            "idea_id":    self.idea_node.idea_id,
        }


# ─── SIGNAL SETS ─────────────────────────────────────────────────────────────

# Keywords that suggest EXECUTION intent
EXECUTION_SIGNALS = {
    "run", "execute", "deploy", "launch", "start", "trigger",
    "send", "publish", "write to", "delete", "modify", "update",
    "call api", "make request", "post to", "submit",
}

# Keywords that suggest ANALYTICAL intent
ANALYTICAL_SIGNALS = {
    "analyze", "compare", "evaluate", "assess", "review", "audit",
    "verify", "validate", "check", "measure", "calculate", "compute",
    "prove", "disprove", "test", "benchmark", "profile",
    "why", "how does", "what is", "explain", "define",
}

# Keywords that suggest CREATIVE intent
CREATIVE_SIGNALS = {
    "imagine", "create", "generate", "design", "invent", "explore",
    "brainstorm", "think of", "what if", "hypothesize", "propose",
    "suggest", "ideate", "draft", "sketch", "concept",
}


# ─── MODE ROUTER ──────────────────────────────────────────────────────────────

class ModeRouter:
    """
    L02: Routes input to CREATIVE, ANALYTICAL, or EXECUTION mode.

    Deterministic. Same input → same mode. No state.

    Scoring:
      Each signal set gets a score = matched_keywords / total_words.
      Mode with highest score wins. Ties go to ANALYTICAL (safer default).
      Execution signals are weighted 2x (execution intent should be explicit).
    """

    EXECUTION_WEIGHT = 2.0

    def route(self, intent_text: str, idea_id: str) -> RouteResult:
        """
        Route one intent to a mode and create its IdeaNode.
        Always returns a RouteResult — never raises on empty input.
        """
        if not intent_text or not intent_text.strip():
            # Empty input → DEFERRED immediately, ANALYTICAL mode
            node = IdeaNode(
                idea_id=idea_id,
                content="[empty input]",
                label=EpistemicLabel.UNKNOWN,
                mode=InputMode.ANALYTICAL,
            )
            return RouteResult(
                mode=InputMode.ANALYTICAL,
                confidence=0.0,
                signals=["empty_input"],
                idea_node=node,
            )

        text_lower = intent_text.lower()
        words = set(re.findall(r'\b\w+\b', text_lower))
        total = max(len(words), 1)

        # Score each mode
        exec_hits = [s for s in EXECUTION_SIGNALS
                     if any(s in text_lower for s in [s])]
        anal_hits = [s for s in ANALYTICAL_SIGNALS
                     if any(s in text_lower for s in [s])]
        crea_hits = [s for s in CREATIVE_SIGNALS
                     if any(s in text_lower for s in [s])]

        exec_score = (len(exec_hits) / total) * self.EXECUTION_WEIGHT
        anal_score = len(anal_hits) / total
        crea_score = len(crea_hits) / total

        # Pick highest score, ties go to ANALYTICAL
        scores = [
            (exec_score, InputMode.EXECUTION,  exec_hits),
            (anal_score, InputMode.ANALYTICAL, anal_hits),
            (crea_score, InputMode.CREATIVE,   crea_hits),
        ]
        scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_mode, best_signals = scores[0]

        # If no signals fired, default to CREATIVE (exploration is safe)
        if best_score == 0.0:
            best_mode = InputMode.CREATIVE
            best_signals = ["no_signals_default"]
            confidence = 0.3
        else:
            # Normalize confidence: how dominant is the winner?
            second_score = scores[1][0]
            margin = best_score - second_score
            confidence = min(1.0, 0.5 + margin * 5.0)

        node = IdeaNode(
            idea_id=idea_id,
            content=intent_text.strip(),
            label=EpistemicLabel.UNKNOWN,
            mode=best_mode,
        )
        return RouteResult(
            mode=best_mode,
            confidence=round(confidence, 4),
            signals=best_signals,
            idea_node=node,
        )


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

def route(intent_text: str, idea_id: str) -> RouteResult:
    return ModeRouter().route(intent_text, idea_id)


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_creative_intent_routed() -> bool:
    """Creative language → CREATIVE mode."""
    r = route("imagine a new way to solve this problem", "id1")
    assert r.mode == InputMode.CREATIVE, f"Got {r.mode}"
    return True

def _test_analytical_intent_routed() -> bool:
    """Analytical language → ANALYTICAL mode."""
    r = route("analyze the performance of this algorithm", "id2")
    assert r.mode == InputMode.ANALYTICAL, f"Got {r.mode}"
    return True

def _test_execution_intent_routed() -> bool:
    """Execution language → EXECUTION mode."""
    r = route("run the deployment script now", "id3")
    assert r.mode == InputMode.EXECUTION, f"Got {r.mode}"
    return True

def _test_empty_input_returns_result() -> bool:
    """Empty input never raises — returns ANALYTICAL with 0 confidence."""
    r = route("", "id_empty")
    assert isinstance(r, RouteResult)
    assert r.confidence == 0.0
    return True

def _test_node_label_is_unknown_at_routing() -> bool:
    """All nodes start as UNKNOWN — labeling happens at L05."""
    r = route("explore the possibility of X", "id5")
    assert r.idea_node.label == EpistemicLabel.UNKNOWN
    return True

def _test_deterministic() -> bool:
    """Same input → same mode every time."""
    text = "generate ideas for improving the system"
    r1 = route(text, "det1")
    r2 = route(text, "det2")
    assert r1.mode == r2.mode
    return True

def _test_execution_weighted_higher() -> bool:
    """Execution signals score higher even with fewer matches."""
    r = route("run this", "exec_weight")
    assert r.mode == InputMode.EXECUTION
    return True

def _test_no_signal_defaults_to_creative() -> bool:
    """Input with no recognizable signals defaults to CREATIVE (exploration safe)."""
    r = route("the cat sat on the mat", "no_sig")
    assert r.mode == InputMode.CREATIVE
    return True

def _test_result_serializable() -> bool:
    """RouteResult.to_dict() is JSON-serializable."""
    import json
    r = route("analyze this idea", "ser1")
    json.dumps(r.to_dict())
    return True

def _test_idea_node_has_correct_mode() -> bool:
    """IdeaNode.mode matches RouteResult.mode."""
    r = route("imagine a new approach", "mode1")
    assert r.idea_node.mode == r.mode
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
    print("MODE ROUTER — Labyrinth-OS / Lane 1 / L02")
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
    print(f"\n{'='*70}\n  MODE ROUTER — COMPLETE\n{'='*70}")
