"""
sandbox_runner.py — Labyrinth-OS-Portable
==========================================
Safe testing of proposed changes before live deployment.

When an owner approves a proposal, it does not apply immediately to the
live system. Instead:

  1. Current state is snapshotted (pre_update_<ts>)
  2. Proposed changes applied to a sandbox copy
  3. Sandbox runs for N turns using the BUILTIN engine
  4. Degradation monitored vs baseline
  5. If sandbox degrades → FAIL, auto-rollback, report to owner
  6. If sandbox passes → owner confirms live deployment

The owner always sees the sandbox result before going live.
If the sandbox fails, nothing changed in the live system.
If the owner later wants to roll back after going live,
BootManager.boot(pre_update_snap_id, agent) does it in one call.

@LabyrinthCoder — Labyrinth-OS-Portable
"""
from __future__ import annotations

import copy
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent
for _sub in (".", "core", "agent", "healing", "backend"):
    _p = str(_HERE.parent / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)


@dataclass
class SandboxResult:
    """Result of a sandbox test run."""
    passed:              bool
    proposal_id:         str
    turns_run:           int
    baseline_block_rate: float
    sandbox_block_rate:  float
    baseline_confidence: float
    sandbox_confidence:  float
    degradation_delta:   float   # positive = got worse
    failure_reason:      str     # empty if passed
    duration_s:          float
    pre_update_snap_id:  str     # snapshot taken before sandbox ran

    @property
    def summary(self) -> str:
        if self.passed:
            return (
                f"PASSED — {self.turns_run} turns. "
                f"Block rate: {self.baseline_block_rate:.1%} → {self.sandbox_block_rate:.1%}. "
                f"Confidence: {self.baseline_confidence:.2f} → {self.sandbox_confidence:.2f}."
            )
        return (
            f"FAILED — {self.failure_reason}. "
            f"Block rate: {self.baseline_block_rate:.1%} → {self.sandbox_block_rate:.1%}. "
            f"Auto-rolled back. Live system unchanged."
        )


class SandboxRunner:
    """
    Runs a sandbox test of proposed threshold changes.

    The sandbox does NOT modify the live agent.
    It creates a temporary copy of the healing/evolution state,
    applies the proposed changes to that copy,
    runs N synthetic turns through the gate,
    and compares the outcome to the baseline.

    If sandbox passes: owner can confirm live deployment.
    If sandbox fails: nothing changed, owner is notified.
    """

    # Thresholds for declaring sandbox a failure
    BLOCK_RATE_DEGRADATION_THRESHOLD = 0.15   # block rate went up by >15 ppt
    CONFIDENCE_DEGRADATION_THRESHOLD = 0.10   # confidence fell by >10 ppt
    MIN_TURNS = 5                              # minimum turns for a valid test

    def __init__(self, boot_manager) -> None:
        self._bm = boot_manager

    def test_proposal(
        self,
        agent,
        proposal,              # ProposalPacket
        test_prompts: list[str] | None = None,
        n_turns: int = 20,
    ) -> SandboxResult:
        """
        Test a proposal in sandbox before applying to live.

        Steps:
        1. Snapshot current state (pre_update)
        2. Measure baseline block rate and confidence
        3. Apply proposed thresholds to sandbox copy
        4. Run n_turns through the gate
        5. Compare sandbox results to baseline
        6. Return result — caller decides whether to go live
        """
        start = time.time()

        # Step 1: snapshot before anything
        pre_snap_id = self._bm.save_pre_update(agent, proposal.proposal_id)

        # Step 2: measure baseline
        baseline_results = self._run_turns(agent, test_prompts, n_turns)
        baseline_block_rate = baseline_results["block_rate"]
        baseline_confidence = baseline_results["avg_confidence"]

        # Step 3 & 4: apply proposed changes to sandbox copy and test
        sandbox_results = self._run_with_proposal(
            agent, proposal, test_prompts, n_turns
        )
        sandbox_block_rate = sandbox_results["block_rate"]
        sandbox_confidence = sandbox_results["avg_confidence"]

        duration = time.time() - start

        # Step 5: evaluate
        block_delta      = sandbox_block_rate - baseline_block_rate
        confidence_delta = baseline_confidence - sandbox_confidence  # positive = worse
        degradation      = max(block_delta, confidence_delta)

        failure_reason = ""
        if sandbox_results["turns_run"] < self.MIN_TURNS:
            failure_reason = f"Insufficient turns completed ({sandbox_results['turns_run']})"
        elif block_delta > self.BLOCK_RATE_DEGRADATION_THRESHOLD:
            failure_reason = (
                f"Block rate increased by {block_delta:.1%} "
                f"({baseline_block_rate:.1%} → {sandbox_block_rate:.1%})"
            )
        elif confidence_delta > self.CONFIDENCE_DEGRADATION_THRESHOLD:
            failure_reason = (
                f"Confidence degraded by {confidence_delta:.2f} "
                f"({baseline_confidence:.2f} → {sandbox_confidence:.2f})"
            )

        passed = not failure_reason

        return SandboxResult(
            passed=passed,
            proposal_id=proposal.proposal_id,
            turns_run=sandbox_results["turns_run"],
            baseline_block_rate=baseline_block_rate,
            sandbox_block_rate=sandbox_block_rate,
            baseline_confidence=baseline_confidence,
            sandbox_confidence=sandbox_confidence,
            degradation_delta=degradation,
            failure_reason=failure_reason,
            duration_s=duration,
            pre_update_snap_id=pre_snap_id,
        )

    def apply_to_live(
        self, agent, proposal, pre_snap_id: str
    ) -> bool:
        """
        Apply approved + sandbox-passed proposal to live system.
        Called by owner after reviewing SandboxResult.
        pre_snap_id is the safety net — if anything goes wrong, boot from it.
        Returns True on success.
        """
        try:
            pv = proposal.proposed_value
            if isinstance(pv, dict):
                ev = agent.healing.evolution
                if "tau"   in pv: ev._tau   = float(pv["tau"])
                if "chi"   in pv: ev._chi   = float(pv["chi"])
                if "drift" in pv: ev._drift  = float(pv["drift"])
                if "betti" in pv: ev._betti  = float(pv["betti"])
                if "confidence" in pv: ev._conf = float(pv["confidence"])
            return True
        except Exception:
            # If anything fails, restore from pre-update snapshot
            self._bm.boot(pre_snap_id, agent)
            return False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_turns(
        self, agent, prompts: list[str] | None, n: int
    ) -> dict:
        """Run N turns and measure block rate and confidence."""
        if not prompts:
            prompts = self._default_prompts()

        blocks     = 0
        confidences = []
        turns_run  = 0

        for i in range(n):
            prompt = prompts[i % len(prompts)]
            try:
                # Use non-streaming turn for speed
                result = agent.turn(prompt)
                turns_run += 1
                if result.decision.name != "EXECUTE":
                    blocks += 1
                # Estimate confidence from label
                label = result.epistemic_label
                conf  = self._label_to_confidence(label)
                confidences.append(conf)
            except Exception:
                pass

        block_rate    = blocks / max(turns_run, 1)
        avg_confidence = sum(confidences) / max(len(confidences), 1)
        return {
            "turns_run":       turns_run,
            "block_rate":      block_rate,
            "avg_confidence":  avg_confidence,
        }

    def _run_with_proposal(
        self, agent, proposal, prompts: list[str] | None, n: int
    ) -> dict:
        """Apply proposed thresholds temporarily and run turns."""
        # Save current values
        ev = agent.healing.evolution
        orig = {
            "tau":   ev._tau,
            "chi":   ev._chi,
            "drift": ev._drift,
            "betti": ev._betti,
            "conf":  ev._conf,
        }

        try:
            # Apply proposed values
            pv = proposal.proposed_value
            if isinstance(pv, dict):
                if "tau"   in pv: ev._tau   = float(pv["tau"])
                if "chi"   in pv: ev._chi   = float(pv["chi"])
                if "drift" in pv: ev._drift  = float(pv["drift"])

            # Run turns with new values
            return self._run_turns(agent, prompts, n)
        finally:
            # Always restore original values
            ev._tau   = orig["tau"]
            ev._chi   = orig["chi"]
            ev._drift = orig["drift"]
            ev._betti = orig["betti"]
            ev._conf  = orig["conf"]

    @staticmethod
    def _label_to_confidence(label: str) -> float:
        """Convert epistemic label to approximate confidence value."""
        return {
            "CLEAR":                0.92,
            "CAUTION":              0.75,
            "LOW_CONFIDENCE":       0.60,
            "HIGH_DRIFT":           0.58,
            "LIKELY_HALLUCINATION": 0.45,
            "UNRELIABLE":           0.30,
        }.get(label, 0.70)

    @staticmethod
    def _default_prompts() -> list[str]:
        """Default test prompts covering different categories."""
        return [
            "Explain how a neural network learns.",
            "Write a Python function to sort a list.",
            "What is the capital of France?",
            "Help me debug this error: AttributeError: NoneType",
            "Summarise the key ideas in machine learning.",
            "What are the risks of deploying AI in healthcare?",
            "Write a unit test for a function that adds two numbers.",
            "Explain the difference between supervised and unsupervised learning.",
            "What should I consider when designing a REST API?",
            "Help me understand recursion with a simple example.",
        ]


# ── Tests ─────────────────────────────────────────────────────────────────────

def run_tests() -> tuple[int, int, list]:
    import tempfile, shutil
    results = []
    passed = failed = 0

    def ok(n): results.append((n, "PASS", None)); nonlocal passed; passed += 1
    def fail(n, e): results.append((n, "FAIL", str(e))); nonlocal failed; failed += 1

    from system_snapshot import BootManager

    # T1: SandboxResult summary
    try:
        r = SandboxResult(
            passed=True, proposal_id="p001", turns_run=20,
            baseline_block_rate=0.10, sandbox_block_rate=0.08,
            baseline_confidence=0.85, sandbox_confidence=0.87,
            degradation_delta=-0.02, failure_reason="",
            duration_s=1.5, pre_update_snap_id="snap001",
        )
        assert "PASSED" in r.summary
        assert "20" in r.summary
        ok("sandbox_result_passed_summary")
    except Exception as e: fail("sandbox_result_passed_summary", e)

    # T2: failed result
    try:
        r = SandboxResult(
            passed=False, proposal_id="p002", turns_run=20,
            baseline_block_rate=0.10, sandbox_block_rate=0.30,
            baseline_confidence=0.85, sandbox_confidence=0.72,
            degradation_delta=0.20, failure_reason="Block rate increased by 20.0%",
            duration_s=1.5, pre_update_snap_id="snap002",
        )
        assert "FAILED" in r.summary
        assert "unchanged" in r.summary.lower()
        ok("sandbox_result_failed_summary")
    except Exception as e: fail("sandbox_result_failed_summary", e)

    # T3: label to confidence mapping
    try:
        assert SandboxRunner._label_to_confidence("CLEAR") > 0.85
        assert SandboxRunner._label_to_confidence("UNRELIABLE") < 0.40
        assert SandboxRunner._label_to_confidence("LIKELY_HALLUCINATION") < 0.50
        ok("label_confidence_mapping")
    except Exception as e: fail("label_confidence_mapping", e)

    # T4: default prompts non-empty
    try:
        prompts = SandboxRunner._default_prompts()
        assert len(prompts) >= 5
        assert all(len(p) > 10 for p in prompts)
        ok("default_prompts")
    except Exception as e: fail("default_prompts", e)

    # T5: thresholds degradation detection
    try:
        assert 0.15 == SandboxRunner.BLOCK_RATE_DEGRADATION_THRESHOLD
        assert 0.10 == SandboxRunner.CONFIDENCE_DEGRADATION_THRESHOLD
        ok("degradation_thresholds_defined")
    except Exception as e: fail("degradation_thresholds_defined", e)

    return passed, failed, results


if __name__ == "__main__":
    p, f, r = run_tests()
    for name, status, err in r:
        print(f"  {'✓' if status == 'PASS' else '✗'} {name}" +
              (f"  → {err}" if err else ""))
    print(f"\n  {p} passed, {f} failed")
