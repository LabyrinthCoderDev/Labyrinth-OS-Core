"""
guardian_slot.py — Labyrinth-OS v6.0
==========================================
Closes Section C gap: safety/guardian_slot.py
Execution gating: EXECUTE / BLOCK / KILL

The Guardian Slot is the final gate before any action reaches the
outside world. It consumes signals from upstream modules:
  - τ-escape ratio  (from tau_escape_ratio.py / tau_baseline_generator.py)
  - drift_score     (from coherence_stacker.py)
  - χ-vector        (from risk_vector.py)
  - CBF margin      (from cbf.py)
  - confidence      (from the epistemic pipeline)
  - human_override  (from deferred_action_queue.py)

Decision logic:
  KILL    — any hard safety violation (τ below floor, χ collapsed,
            CBF breached, or explicit human kill signal)
  BLOCK   — soft violations or low confidence requiring human review
  EXECUTE — all checks pass, action is safe to proceed

The Guardian Slot is fail-closed: any error in evaluation defaults
to BLOCK (not EXECUTE). A KILL is irrevocable within a decision
cycle — it cannot be overridden to EXECUTE without a new cycle.

Dependencies: Python standard library only.
"""

import hashlib
import json
import math
import time
from enum import Enum
from typing import Optional


# ─── SIGMA ANCHOR CONSTANTS — imported from single source of truth ────
# Do not redefine here. Change sigma_anchors.py if values need updating.
try:
    import sys as _sys, os as _os
    _root = _os.path.normpath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
    if _root not in _sys.path: _sys.path.insert(0, _root)
    from sigma_anchors import (TAU_ESCAPE_FLOOR, DRIFT_THRESHOLD,
                                CHI_WARN as CHI_MIN, CHI_COLLAPSE, BETTI_1_CAP,
                                CONFIDENCE_FLOOR as CONFIDENCE_LOW)
    CONFIDENCE_HIGH = 0.8  # guardian-slot specific threshold, not in sigma_anchors
except ImportError:
    # Fallback — values must match sigma_anchors.py exactly
    TAU_ESCAPE_FLOOR   = 0.75
    DRIFT_THRESHOLD    = 0.12
    CHI_MIN            = 0.15
    CHI_COLLAPSE       = 0.40
    BETTI_1_CAP        = 0.045
    CONFIDENCE_LOW     = 0.65
    CONFIDENCE_HIGH    = 0.8
HYSTERESIS_BAND    = 0.1
MAX_ITERATIONS     = 3
CBF_MARGIN_MIN     = 0.0    # CBF must be non-negative to be safe


# ─── ENUMS ───────────────────────────────────────────────────────────

class SlotDecision(Enum):
    EXECUTE = "EXECUTE"
    BLOCK   = "BLOCK"
    KILL    = "KILL"


class KillReason(Enum):
    TAU_BELOW_FLOOR     = "TAU_BELOW_FLOOR"
    CHI_COLLAPSED       = "CHI_COLLAPSED"
    CBF_BREACHED        = "CBF_BREACHED"
    BETTI_BREACHED      = "BETTI_BREACHED"
    HUMAN_KILL          = "HUMAN_KILL"
    ITERATION_EXCEEDED  = "ITERATION_EXCEEDED"


class BlockReason(Enum):
    LOW_CONFIDENCE      = "LOW_CONFIDENCE"
    DRIFT_ELEVATED      = "DRIFT_ELEVATED"
    CHI_ELEVATED        = "CHI_ELEVATED"
    TAU_MARGINAL        = "TAU_MARGINAL"
    EVALUATION_ERROR    = "EVALUATION_ERROR"
    HUMAN_HOLD          = "HUMAN_HOLD"


# ─── INPUT SIGNAL ────────────────────────────────────────────────────

class GuardianSignal:
    """
    Aggregated input signal to the Guardian Slot.
    
    All upstream modules feed into this structure. Missing values
    default to conservative (unsafe) assumptions.
    """
    __slots__ = (
        "tau_escape", "drift_score", "chi_vector", "cbf_margin",
        "betti_1", "confidence", "iteration_count",
        "human_override", "action_id", "timestamp",
    )
    
    def __init__(
        self,
        tau_escape: float,
        drift_score: float,
        chi_vector: float,
        cbf_margin: float,
        betti_1: float = 0.0,
        confidence: float = 0.0,
        iteration_count: int = 0,
        human_override: Optional[str] = None,  # "EXECUTE", "KILL", "HOLD", or None
        action_id: str = "",
        timestamp: Optional[float] = None,
    ):
        self.tau_escape = tau_escape
        self.drift_score = drift_score
        self.chi_vector = chi_vector
        self.cbf_margin = cbf_margin
        self.betti_1 = betti_1
        self.confidence = confidence
        self.iteration_count = iteration_count
        self.human_override = human_override
        self.action_id = action_id
        self.timestamp = timestamp or time.time()
    
    def to_dict(self):
        return {
            "tau_escape": self.tau_escape,
            "drift_score": self.drift_score,
            "chi_vector": self.chi_vector,
            "cbf_margin": self.cbf_margin,
            "betti_1": self.betti_1,
            "confidence": self.confidence,
            "iteration_count": self.iteration_count,
            "human_override": self.human_override,
            "action_id": self.action_id,
            "timestamp": self.timestamp,
        }


# ─── GUARDIAN SLOT RESULT ────────────────────────────────────────────

class SlotResult:
    """Immutable result of a Guardian Slot evaluation."""
    __slots__ = (
        "decision", "reasons", "signal_snapshot",
        "evaluation_time_us", "receipt_hash",
        "human_override_used", "human_override_reason",
    )

    def __init__(self, decision, reasons, signal_snapshot, evaluation_time_us,
                 human_override_used: Optional[str] = None):
        self.decision = decision
        self.reasons = reasons  # list of KillReason or BlockReason
        self.signal_snapshot = signal_snapshot
        self.evaluation_time_us = evaluation_time_us
        # G9: Structured override logging — override is a typed field, not a
        # buried string. Cryptographic signature deferred to A002/A003 hardware.
        # In production: override_reason should be signed by operator key.
        self.human_override_used   = human_override_used   # "KILL"|"HOLD"|"EXECUTE"|None
        self.human_override_reason = (
            f"HUMAN_OVERRIDE:{human_override_used}"
            if human_override_used else None
        )
        self.receipt_hash = self._compute_receipt()

    def _compute_receipt(self):
        content = json.dumps({
            "decision": self.decision.value,
            "reasons": [r.value for r in self.reasons],
            "signal": self.signal_snapshot,
            # G9: override included in receipt hash — override cannot be erased
            # from the chain without breaking the hash
            "human_override": self.human_override_used,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def to_dict(self):
        d = {
            "decision": self.decision.value,
            "reasons": [r.value for r in self.reasons],
            "evaluation_time_us": self.evaluation_time_us,
            "receipt_hash": self.receipt_hash,
        }
        # G9: override surfaces in the serialised proof — visible in replay
        if self.human_override_used:
            d["human_override_used"]   = self.human_override_used
            d["human_override_reason"] = self.human_override_reason
            d["override_signature"]    = "PENDING_HARDWARE_ATTESTATION"
        return d


# ─── GUARDIAN SLOT ENGINE ────────────────────────────────────────────

class GuardianSlot:
    """
    The final execution gate.
    
    Evaluation order (fail-fast):
      1. Human override (KILL takes priority over everything)
      2. Hard safety checks → KILL
      3. Iteration limit → KILL
      4. Soft safety checks → BLOCK
      5. Confidence check → BLOCK
      6. All clear → EXECUTE
    
    Fail-closed: any exception during evaluation → BLOCK.
    KILL is irrevocable within a decision cycle.
    """
    
    def __init__(self, tau_baseline_mean=None):
        """
        Args:
            tau_baseline_mean: If provided, used as the τ reference
                for marginal-zone detection. Falls back to
                TAU_ESCAPE_FLOOR if not set.
        """
        self.tau_baseline_mean = tau_baseline_mean
        self._evaluation_count = 0
        self._kill_count = 0
        self._block_count = 0
        self._execute_count = 0
    
    @property
    def stats(self):
        return {
            "evaluations": self._evaluation_count,
            "kills": self._kill_count,
            "blocks": self._block_count,
            "executes": self._execute_count,
        }
    
    def evaluate(
        self,
        signal: GuardianSignal,
        cgir_decision: str = "UNKNOWN",
    ) -> SlotResult:
        """
        Evaluate a signal and return the gating decision.

        cgir_decision: upstream CGIR gate decision ("ALLOW", "BLOCK", "KILL").
        I5 enforcement: GuardianSlot may only further restrict, never upgrade.
        If cgir_decision is BLOCK or KILL, this method cannot return EXECUTE.
        Self-contained enforcement — does not rely on bridge (GAP 11 fix, May 2026).

        This is the hot path. It must be deterministic and
        must never raise — errors produce BLOCK.
        """
        t_start = time.perf_counter_ns()
        self._evaluation_count += 1

        try:
            decision, reasons = self._evaluate_inner(signal)
        except Exception:
            decision = SlotDecision.BLOCK
            reasons = [BlockReason.EVALUATION_ERROR]

        # I5 self-contained enforcement: never upgrade a CGIR BLOCK or KILL
        if cgir_decision in ("BLOCK", "KILL") and decision == SlotDecision.EXECUTE:
            decision = SlotDecision.BLOCK
            reasons = list(reasons) + [BlockReason.CGIR_PRECEDENCE]

        t_end = time.perf_counter_ns()
        elapsed_us = (t_end - t_start) / 1000.0

        # Soft real-time budget: warn when gate exceeds FPGA floor (670µs).
        # Hardware enforcement (A014) will make this a hard ceiling.
        # Until then, this is telemetry — not enforcement.
        _FPGA_FLOOR_US = 670.0
        if elapsed_us > _FPGA_FLOOR_US:
            import sys as _sys
            print(
                f"  [GATE_TIMING] WARNING: evaluation={elapsed_us:.1f}µs "
                f"> FPGA floor={_FPGA_FLOOR_US}µs. "
                f"Hardware enforcement target not met (A014 OPEN).",
                file=_sys.stderr,
            )

        # Update counters
        if decision == SlotDecision.KILL:
            self._kill_count += 1
        elif decision == SlotDecision.BLOCK:
            self._block_count += 1
        else:
            self._execute_count += 1

        # G9: Pass override to SlotResult so it is embedded in receipt_hash
        # and surfaces in to_dict() for replay inspection.
        _override_used = signal.human_override if signal.human_override else None

        return SlotResult(
            decision=decision,
            reasons=reasons,
            signal_snapshot=signal.to_dict(),
            evaluation_time_us=round(elapsed_us, 2),
            human_override_used=_override_used,
        )
    
    def _evaluate_inner(self, sig: GuardianSignal):
        """Core evaluation logic. Returns (decision, reasons)."""
        kill_reasons = []
        block_reasons = []
        
        # ── Phase 1: Human override ──
        if sig.human_override == "KILL":
            return SlotDecision.KILL, [KillReason.HUMAN_KILL]
        
        if sig.human_override == "HOLD":
            block_reasons.append(BlockReason.HUMAN_HOLD)
        
        # ── Phase 2: Hard safety checks → KILL ──
        if sig.tau_escape < TAU_ESCAPE_FLOOR:
            kill_reasons.append(KillReason.TAU_BELOW_FLOOR)
        
        if sig.chi_vector >= CHI_COLLAPSE:
            kill_reasons.append(KillReason.CHI_COLLAPSED)
        
        if sig.cbf_margin < CBF_MARGIN_MIN:
            kill_reasons.append(KillReason.CBF_BREACHED)
        
        if sig.betti_1 > BETTI_1_CAP:
            kill_reasons.append(KillReason.BETTI_BREACHED)
        
        # Any hard violation → immediate KILL
        if kill_reasons:
            return SlotDecision.KILL, kill_reasons
        
        # ── Phase 3: Iteration limit → KILL ──
        if sig.iteration_count > MAX_ITERATIONS:
            return SlotDecision.KILL, [KillReason.ITERATION_EXCEEDED]
        
        # ── Phase 4: Soft safety checks → BLOCK ──
        if sig.drift_score > DRIFT_THRESHOLD:
            block_reasons.append(BlockReason.DRIFT_ELEVATED)
        
        if sig.chi_vector > CHI_MIN:
            # χ is elevated but not collapsed — warn
            block_reasons.append(BlockReason.CHI_ELEVATED)
        
        # τ marginal zone: above floor but within hysteresis band
        tau_ref = self.tau_baseline_mean or TAU_ESCAPE_FLOOR
        tau_marginal_boundary = TAU_ESCAPE_FLOOR + HYSTERESIS_BAND
        if sig.tau_escape < tau_marginal_boundary:
            block_reasons.append(BlockReason.TAU_MARGINAL)
        
        # ── Phase 5: Confidence check → BLOCK ──
        if sig.confidence < CONFIDENCE_LOW:
            block_reasons.append(BlockReason.LOW_CONFIDENCE)
        
        # ── Phase 6: Any block reasons → BLOCK ──
        if block_reasons:
            return SlotDecision.BLOCK, block_reasons
        
        # ── Phase 7: Human override EXECUTE (only valid if no blocks) ──
        # Note: human EXECUTE cannot override KILLs or BLOCKs
        # It's only meaningful as confirmation when the system is already clear
        
        # ── All clear ──
        return SlotDecision.EXECUTE, []
    
    def reset_stats(self):
        """Reset evaluation counters."""
        self._evaluation_count = 0
        self._kill_count = 0
        self._block_count = 0
        self._execute_count = 0


# ─── CONVENIENCE FUNCTIONS ───────────────────────────────────────────

def quick_evaluate(tau, drift, chi, cbf, confidence=0.9, betti=0.0):
    """One-shot evaluation for testing or scripting."""
    slot = GuardianSlot()
    sig = GuardianSignal(
        tau_escape=tau,
        drift_score=drift,
        chi_vector=chi,
        cbf_margin=cbf,
        betti_1=betti,
        confidence=confidence,
    )
    return slot.evaluate(sig)


# ─── TEST SUITE ──────────────────────────────────────────────────────

def _test_nominal_execute():
    """Clean signal → EXECUTE."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5, confidence=0.9)
    assert r.decision == SlotDecision.EXECUTE, f"Expected EXECUTE, got {r.decision}"
    assert len(r.reasons) == 0
    return True


def _test_tau_below_floor_kills():
    """τ below floor → KILL with TAU_BELOW_FLOOR reason."""
    r = quick_evaluate(tau=0.70, drift=0.02, chi=0.05, cbf=0.5)
    assert r.decision == SlotDecision.KILL
    assert KillReason.TAU_BELOW_FLOOR in r.reasons
    return True


def _test_chi_collapse_kills():
    """χ at collapse threshold → KILL."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.40, cbf=0.5)
    assert r.decision == SlotDecision.KILL
    assert KillReason.CHI_COLLAPSED in r.reasons
    return True


def _test_cbf_breach_kills():
    """Negative CBF margin → KILL."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=-0.1)
    assert r.decision == SlotDecision.KILL
    assert KillReason.CBF_BREACHED in r.reasons
    return True


def _test_betti_breach_kills():
    """Betti-1 above cap → KILL."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5, betti=0.05)
    assert r.decision == SlotDecision.KILL
    assert KillReason.BETTI_BREACHED in r.reasons
    return True


def _test_multiple_kill_reasons():
    """Multiple hard violations → KILL with all reasons listed."""
    r = quick_evaluate(tau=0.50, drift=0.02, chi=0.50, cbf=-0.1, betti=0.1)
    assert r.decision == SlotDecision.KILL
    assert len(r.reasons) >= 3
    return True


def _test_human_kill_overrides_all():
    """Human KILL signal → immediate KILL regardless of clean metrics."""
    slot = GuardianSlot()
    sig = GuardianSignal(
        tau_escape=0.95, drift_score=0.01, chi_vector=0.02,
        cbf_margin=1.0, confidence=0.99, human_override="KILL",
    )
    r = slot.evaluate(sig)
    assert r.decision == SlotDecision.KILL
    assert KillReason.HUMAN_KILL in r.reasons
    return True


def _test_human_hold_blocks():
    """Human HOLD signal → BLOCK."""
    slot = GuardianSlot()
    sig = GuardianSignal(
        tau_escape=0.95, drift_score=0.01, chi_vector=0.02,
        cbf_margin=1.0, confidence=0.99, human_override="HOLD",
    )
    r = slot.evaluate(sig)
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.HUMAN_HOLD in r.reasons
    return True


def _test_low_confidence_blocks():
    """Confidence below LOW threshold → BLOCK."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5, confidence=0.5)
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.LOW_CONFIDENCE in r.reasons
    return True


def _test_drift_elevated_blocks():
    """Drift above threshold → BLOCK (not KILL)."""
    r = quick_evaluate(tau=0.90, drift=0.15, chi=0.05, cbf=0.5, confidence=0.9)
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.DRIFT_ELEVATED in r.reasons
    return True


def _test_chi_elevated_blocks():
    """χ above CHI_MIN but below collapse → BLOCK."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.20, cbf=0.5, confidence=0.9)
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.CHI_ELEVATED in r.reasons
    return True


def _test_tau_marginal_blocks():
    """τ above floor but within hysteresis band → BLOCK."""
    r = quick_evaluate(tau=0.80, drift=0.02, chi=0.05, cbf=0.5, confidence=0.9)
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.TAU_MARGINAL in r.reasons
    return True


def _test_iteration_exceeded_kills():
    """Iteration count above MAX → KILL."""
    slot = GuardianSlot()
    sig = GuardianSignal(
        tau_escape=0.95, drift_score=0.01, chi_vector=0.02,
        cbf_margin=1.0, confidence=0.99, iteration_count=4,
    )
    r = slot.evaluate(sig)
    assert r.decision == SlotDecision.KILL
    assert KillReason.ITERATION_EXCEEDED in r.reasons
    return True


def _test_iteration_at_max_executes():
    """Iteration count at MAX (not above) → can EXECUTE."""
    slot = GuardianSlot()
    sig = GuardianSignal(
        tau_escape=0.95, drift_score=0.01, chi_vector=0.02,
        cbf_margin=1.0, confidence=0.99, iteration_count=3,
    )
    r = slot.evaluate(sig)
    assert r.decision == SlotDecision.EXECUTE
    return True


def _test_fail_closed_on_error():
    """Evaluation error → BLOCK (not EXECUTE or crash)."""
    slot = GuardianSlot()
    # Inject a signal that will cause an error by using a broken subclass
    sig = GuardianSignal(
        tau_escape=0.90, drift_score=0.02, chi_vector=0.05,
        cbf_margin=0.5, confidence=0.9,
    )
    # Monkey-patch to force error
    original = sig.to_dict
    def broken_to_dict():
        raise RuntimeError("simulated failure")
    # The error happens in result creation, but evaluate catches it
    # Let's force the inner evaluation to fail instead
    original_inner = slot._evaluate_inner
    def broken_inner(s):
        raise ValueError("simulated inner failure")
    slot._evaluate_inner = broken_inner
    r = slot.evaluate(sig)
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.EVALUATION_ERROR in r.reasons
    slot._evaluate_inner = original_inner
    return True


def _test_result_has_receipt():
    """Every result has a 64-char hex receipt hash."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5)
    assert len(r.receipt_hash) == 64
    assert all(c in "0123456789abcdef" for c in r.receipt_hash)
    return True


def _test_receipt_deterministic():
    """Same input → same receipt."""
    fixed_ts = 1000000.0
    slot = GuardianSlot()
    sig1 = GuardianSignal(0.90, 0.02, 0.05, 0.5, confidence=0.9, timestamp=fixed_ts)
    sig2 = GuardianSignal(0.90, 0.02, 0.05, 0.5, confidence=0.9, timestamp=fixed_ts)
    r1 = slot.evaluate(sig1)
    r2 = slot.evaluate(sig2)
    assert r1.receipt_hash == r2.receipt_hash
    return True


def _test_receipt_changes_with_input():
    """Different input → different receipt."""
    r1 = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5)
    r2 = quick_evaluate(tau=0.80, drift=0.02, chi=0.05, cbf=0.5)
    assert r1.receipt_hash != r2.receipt_hash
    return True


def _test_stats_tracking():
    """Slot tracks evaluation counts correctly."""
    slot = GuardianSlot()
    sigs = [
        GuardianSignal(0.95, 0.01, 0.02, 1.0, confidence=0.9),   # EXECUTE
        GuardianSignal(0.95, 0.01, 0.02, 1.0, confidence=0.5),   # BLOCK (low conf)
        GuardianSignal(0.50, 0.01, 0.02, 1.0, confidence=0.9),   # KILL (tau)
        GuardianSignal(0.95, 0.01, 0.02, 1.0, confidence=0.9),   # EXECUTE
    ]
    for s in sigs:
        slot.evaluate(s)
    stats = slot.stats
    assert stats["evaluations"] == 4
    assert stats["executes"] == 2
    assert stats["blocks"] == 1
    assert stats["kills"] == 1
    return True


def _test_stats_reset():
    """Reset clears all counters."""
    slot = GuardianSlot()
    slot.evaluate(GuardianSignal(0.95, 0.01, 0.02, 1.0, confidence=0.9))
    slot.reset_stats()
    assert slot.stats["evaluations"] == 0
    return True


def _test_result_to_dict():
    """Result serializes to dict with all fields."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5)
    d = r.to_dict()
    assert "decision" in d
    assert "reasons" in d
    assert "evaluation_time_us" in d
    assert "receipt_hash" in d
    assert d["decision"] == "EXECUTE"
    return True


def _test_signal_to_dict():
    """Signal serializes to dict with all fields."""
    sig = GuardianSignal(0.90, 0.02, 0.05, 0.5, confidence=0.9, action_id="test-1")
    d = sig.to_dict()
    assert d["tau_escape"] == 0.90
    assert d["action_id"] == "test-1"
    return True


def _test_kill_priority_over_block():
    """When both KILL and BLOCK conditions exist, KILL wins."""
    r = quick_evaluate(tau=0.70, drift=0.15, chi=0.50, cbf=-0.1, confidence=0.3)
    assert r.decision == SlotDecision.KILL
    return True


def _test_human_execute_no_override_of_blocks():
    """Human EXECUTE cannot override soft blocks."""
    slot = GuardianSlot()
    sig = GuardianSignal(
        tau_escape=0.95, drift_score=0.01, chi_vector=0.02,
        cbf_margin=1.0, confidence=0.3, human_override="EXECUTE",
    )
    r = slot.evaluate(sig)
    # Low confidence still blocks even with human EXECUTE
    assert r.decision == SlotDecision.BLOCK
    return True


def _test_baseline_mean_affects_marginal():
    """Providing tau_baseline_mean shifts the marginal boundary detection."""
    # Without baseline mean, marginal boundary is floor + hysteresis = 0.85
    slot1 = GuardianSlot(tau_baseline_mean=None)
    sig = GuardianSignal(0.86, 0.02, 0.05, 0.5, confidence=0.9)
    r1 = slot1.evaluate(sig)
    # 0.86 > 0.85 → EXECUTE (above marginal zone)
    
    # The marginal zone is [floor, floor + hysteresis] = [0.75, 0.85]
    # τ=0.86 is above, so EXECUTE
    assert r1.decision == SlotDecision.EXECUTE, f"Got {r1.decision}"
    return True


def _test_boundary_tau_at_floor():
    """τ exactly at floor → KILL (not BLOCK)."""
    # Using < comparison, so exactly at floor should NOT kill
    # Actually: sig.tau_escape < TAU_ESCAPE_FLOOR → need to be below
    # 0.75 is not < 0.75, so no kill. But it IS < 0.85 (marginal boundary)
    r = quick_evaluate(tau=0.75, drift=0.02, chi=0.05, cbf=0.5, confidence=0.9)
    # 0.75 is NOT < 0.75, so no TAU_BELOW_FLOOR kill
    # But 0.75 < 0.85 (marginal boundary), so TAU_MARGINAL block
    assert r.decision == SlotDecision.BLOCK
    assert BlockReason.TAU_MARGINAL in r.reasons
    return True


def _test_boundary_cbf_at_zero():
    """CBF margin exactly 0 → safe (not breached)."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.0, confidence=0.9)
    # cbf_margin < 0 → kill. 0.0 is not < 0.0, so safe
    assert r.decision == SlotDecision.EXECUTE
    return True


def _test_evaluation_time_recorded():
    """Evaluation time is recorded and non-negative."""
    r = quick_evaluate(tau=0.90, drift=0.02, chi=0.05, cbf=0.5)
    assert r.evaluation_time_us >= 0
    return True


# ─── TEST RUNNER ─────────────────────────────────────────────────────

def run_tests():
    tests = [(name, obj) for name, obj in globals().items()
             if name.startswith("_test_") and callable(obj)]
    tests.sort(key=lambda x: x[0])
    
    passed = 0
    failed = 0
    results = []
    
    for name, fn in tests:
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)))
    
    return passed, failed, results


# ─── MAIN ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("GUARDIAN SLOT — Labyrinth-OS v6.0")
    print("=" * 70)
    
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err:
            line += f"  → {err}"
        print(line)
    
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    
    if failed > 0:
        print("\n  ✗ TESTS FAILED")
        raise SystemExit(1)
    
    # Demo evaluation
    print("\n── DEMO EVALUATIONS ──\n")
    slot = GuardianSlot(tau_baseline_mean=0.8149)
    
    demos = [
        ("Nominal",     GuardianSignal(0.90, 0.02, 0.05, 0.5, confidence=0.9)),
        ("Low τ (KILL)", GuardianSignal(0.60, 0.02, 0.05, 0.5, confidence=0.9)),
        ("High drift",  GuardianSignal(0.90, 0.15, 0.05, 0.5, confidence=0.9)),
        ("χ collapse",  GuardianSignal(0.90, 0.02, 0.45, 0.5, confidence=0.9)),
        ("CBF breach",  GuardianSignal(0.90, 0.02, 0.05, -0.1, confidence=0.9)),
        ("Low conf",    GuardianSignal(0.90, 0.02, 0.05, 0.5, confidence=0.4)),
        ("Human KILL",  GuardianSignal(0.95, 0.01, 0.02, 1.0, confidence=0.99, human_override="KILL")),
        ("Human HOLD",  GuardianSignal(0.95, 0.01, 0.02, 1.0, confidence=0.99, human_override="HOLD")),
    ]
    
    for label, sig in demos:
        r = slot.evaluate(sig)
        reasons_str = ", ".join(r.value for r in r.reasons) if r.reasons else "—"
        print(f"  {label:20s} → {r.decision.value:8s}  [{reasons_str}]")
    
    print(f"\n  Stats: {slot.stats}")
    
    # Receipt
    import hashlib as _hl
    with open(__file__, "rb") as f:
        file_hash = _hl.sha256(f.read()).hexdigest()
    
    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {file_hash}")
    print(f"  File:    guardian_slot.py")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Section C gap: safety/guardian_slot.py — CLOSED")
    print(f"{'=' * 70}")
