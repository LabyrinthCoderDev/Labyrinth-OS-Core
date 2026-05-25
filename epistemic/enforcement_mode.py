"""
enforcement_mode.py — Labyrinth-OS-Portable
=============================================
Single parameter controlling how the constitutional gate responds
to a failed check.

EnforcementMode.HARD — for robots and physical systems
  EXECUTE / BLOCK / KILL
  KILL means stop immediately. Servo cut. No negotiation.
  Layer 0 PhysicsSentinel runs before the pipeline.
  Correct for anything that can cause physical harm.

EnforcementMode.SOFT — for agents and consumer apps
  EXECUTE + honest epistemic labels
  CLEAR / CAUTION / LOW_CONFIDENCE / HIGH_DRIFT /
  LIKELY_HALLUCINATION / UNRELIABLE
  Nothing hard-stops. User or operator sees the label and decides.
  Correct for software agents, consumer apps, anything the user owns.

The gate is identical in both modes.
The sigma anchor thresholds are identical.
The Z3-proven constants are identical.
The WORM ledger logs either way.
Only the response to a failed check changes.

@LabyrinthCoder — Labyrinth-OS-Portable
"""
from __future__ import annotations
from enum import Enum


class EnforcementMode(str, Enum):
    """
    Controls what happens after the constitutional gate fires.

    HARD: physical systems. KILL is correct. Operator takes over.
    SOFT: software agents. Honest label. User decides.
    """
    HARD = "HARD"
    SOFT = "SOFT"

    def is_hard(self) -> bool:
        return self == EnforcementMode.HARD

    def is_soft(self) -> bool:
        return self == EnforcementMode.SOFT

    def kill_label(self) -> str:
        """What a KILL decision becomes in this mode."""
        if self.is_hard():
            return "KILL"
        return "UNRELIABLE"

    def block_label(self) -> str:
        """What a BLOCK decision becomes in this mode."""
        if self.is_hard():
            return "BLOCK"
        return "LIKELY_HALLUCINATION"

    def describe(self) -> str:
        if self.is_hard():
            return (
                "HARD — physical enforcement. "
                "KILL = immediate stop. For robots and hardware."
            )
        return (
            "SOFT — epistemic labels. "
            "No hard stops. Honest labels. User decides. For agents and apps."
        )


def apply_enforcement_mode(
    decision: str,
    mode:     EnforcementMode,
) -> str:
    """
    Translate a raw gate decision into the appropriate output
    for the given enforcement mode.

    In HARD mode: decisions pass through unchanged.
    In SOFT mode: KILL → UNRELIABLE, BLOCK → LIKELY_HALLUCINATION.

    EXECUTE always passes through in both modes.
    """
    if mode.is_hard():
        return decision

    # SOFT mode — no hard stops
    translation = {
        "KILL":  "UNRELIABLE",
        "BLOCK": "LIKELY_HALLUCINATION",
    }
    return translation.get(decision, decision)


# ── Tests ─────────────────────────────────────────────────────────────────────

def run_tests() -> tuple[int, int, list]:
    results = []
    passed = failed = 0

    def ok(n): results.append((n, "PASS", None)); nonlocal passed; passed += 1
    def fail(n, e): results.append((n, "FAIL", str(e))); nonlocal failed; failed += 1

    # T1: HARD mode passes KILL through
    try:
        assert apply_enforcement_mode("KILL",    EnforcementMode.HARD) == "KILL"
        assert apply_enforcement_mode("BLOCK",   EnforcementMode.HARD) == "BLOCK"
        assert apply_enforcement_mode("EXECUTE", EnforcementMode.HARD) == "EXECUTE"
        ok("hard_mode_passthrough")
    except Exception as e: fail("hard_mode_passthrough", e)

    # T2: SOFT mode translates KILL and BLOCK
    try:
        assert apply_enforcement_mode("KILL",    EnforcementMode.SOFT) == "UNRELIABLE"
        assert apply_enforcement_mode("BLOCK",   EnforcementMode.SOFT) == "LIKELY_HALLUCINATION"
        assert apply_enforcement_mode("EXECUTE", EnforcementMode.SOFT) == "EXECUTE"
        ok("soft_mode_translation")
    except Exception as e: fail("soft_mode_translation", e)

    # T3: EXECUTE identical in both modes
    try:
        for mode in (EnforcementMode.HARD, EnforcementMode.SOFT):
            assert apply_enforcement_mode("EXECUTE", mode) == "EXECUTE"
        ok("execute_identical_both_modes")
    except Exception as e: fail("execute_identical_both_modes", e)

    # T4: mode properties
    try:
        assert EnforcementMode.HARD.is_hard()
        assert not EnforcementMode.HARD.is_soft()
        assert EnforcementMode.SOFT.is_soft()
        assert not EnforcementMode.SOFT.is_hard()
        ok("mode_properties")
    except Exception as e: fail("mode_properties", e)

    # T5: kill_label and block_label
    try:
        assert EnforcementMode.HARD.kill_label()  == "KILL"
        assert EnforcementMode.SOFT.kill_label()  == "UNRELIABLE"
        assert EnforcementMode.HARD.block_label() == "BLOCK"
        assert EnforcementMode.SOFT.block_label() == "LIKELY_HALLUCINATION"
        ok("label_methods")
    except Exception as e: fail("label_methods", e)

    # T6: string value
    try:
        assert EnforcementMode.HARD == "HARD"
        assert EnforcementMode.SOFT == "SOFT"
        ok("string_enum")
    except Exception as e: fail("string_enum", e)

    # T7: describe is informative
    try:
        assert "KILL" in EnforcementMode.HARD.describe()
        assert "label" in EnforcementMode.SOFT.describe()
        ok("describe")
    except Exception as e: fail("describe", e)

    return passed, failed, results


if __name__ == "__main__":
    p, f, r = run_tests()
    for name, status, err in r:
        print(f"  {'✓' if status == 'PASS' else '✗'} {name}" +
              (f"  → {err}" if err else ""))
    print(f"\n  {p} passed, {f} failed")
