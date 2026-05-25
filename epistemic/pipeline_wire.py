"""
pipeline_wire.py — Labyrinth-OS / System Flow
===============================================
Pipeline Wiring — Mandatory Flow Enforcement

MANDATORY FLOW:
  INPUT → LABELING → ARCHIVE → PROMOTION
  → REALITY_GATE → CGIR → GATE → AEGIS → LEDGER
  → REPLAY → OBSERVABILITY → GOVERNANCE → FEEDBACK → ARCHIVE

TIMESTAMP FIELDS (replaces plain booleans — ordering now provable):
  labeling_complete:     Optional[float]  — Unix time when LABELING passed
  archive_complete:      Optional[float]  — Unix time when ARCHIVE passed
  promotion_complete:    Optional[float]  — Unix time when PROMOTION passed
  reality_gate_pre_cgir: Optional[float]  — Unix time when GATE passed (before CGIR)
  execution_logged:      Optional[float]  — Unix time when LEDGER passed
  replay_completed:      Optional[float]  — Unix time when REPLAY passed

  None  = stage not yet passed
  float = Unix timestamp at which stage passed

Ordering is now provable:
  archive_complete > labeling_complete
  promotion_complete > archive_complete
  reality_gate_pre_cgir > promotion_complete
  reality_gate_pre_cgir < cgir_entered

LABELING_REQUIRED FLAG:
  labeling_required = True  (default)
    → labeling_complete must be set before assert_can_enter_cgir() passes
  labeling_required = False (ignition Option B)
    → labeling check skipped — EXPLICIT DECLARATION, not implicit bypass
    → ARCHIVE → PROMOTION → REALITY_GATE still mandatory
    → Option B is a controlled exception, not a backdoor

FATAL ENFORCEMENT:
  assert_can_enter_cgir() raises SystemError (not ValueError):
    - labeling_required=True AND labeling_complete is None
    - archive_complete is None
    - promotion_complete is None
    - reality_gate_pre_cgir is None

COUNCIL ROLE (enforced here by doctrine):
  Council = LABELING AUTHORITY ONLY.
  Council labels signal trust. Council does NOT promote.

References:
  ARCHITECTURE.md — mandatory pipeline
  INVARIANTS.md   — I1-I10
  KNOWN_GAPS.md   — GAP 1 (Option B, labeling_required=False)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional


NO_TRACE_ERROR = (
    "NO_TRACE: Execution attempted without PipelineTrace — structurally invalid"
)


@unique
class PipelineStage(str, Enum):
    INPUT          = "INPUT"
    LABELING       = "LABELING"
    ARCHIVE        = "ARCHIVE"
    DEFERRED       = "DEFERRED"
    PROMOTION      = "PROMOTION"
    REALITY_GATE   = "REALITY_GATE"
    CGIR           = "CGIR"
    GATE           = "GATE"
    AEGIS          = "AEGIS"
    LEDGER         = "LEDGER"
    REPLAY         = "REPLAY"
    OBSERVABILITY  = "OBSERVABILITY"
    GOVERNANCE     = "GOVERNANCE"
    FEEDBACK       = "FEEDBACK"
    FAILOVER_ENTRY = "FAILOVER_ENTRY"

    @property
    def order(self) -> int:
        ORDER = [
            "INPUT", "LABELING", "ARCHIVE", "DEFERRED",
            "PROMOTION", "REALITY_GATE", "CGIR", "GATE",
            "AEGIS", "LEDGER", "REPLAY", "OBSERVABILITY",
            "GOVERNANCE", "FEEDBACK",
        ]
        try:
            return ORDER.index(self.value)
        except ValueError:
            return -1

    @classmethod
    def failover_allowed(cls, stage: "PipelineStage") -> bool:
        return stage in (cls.FAILOVER_ENTRY, cls.INPUT)


@dataclass
class PipelineTrace:
    """
    Trace of one unit through the mandatory pipeline.

    TIMESTAMP FIELDS — None = not passed. float = Unix time when passed.
    Append-only: None → float only. Never overwrite.

    labeling_required=False → Option B explicit declaration.
    Still requires ARCHIVE → PROMOTION → REALITY_GATE.
    """
    input_id:          str
    labeling_required: bool = True

    labeling_complete:     Optional[float] = None
    archive_complete:      Optional[float] = None
    promotion_complete:    Optional[float] = None
    reality_gate_pre_cgir: Optional[float] = None
    execution_logged:      Optional[float] = None
    replay_completed:      Optional[float] = None

    _cgir_entered:     float = field(default=0.0, repr=False)
    _logical_sequence: int   = field(default=0,   repr=False)  # GAP 12: monotonic counter
    stages:            List[Dict[str, Any]] = field(default_factory=list)
    rejected_at:   Optional[str] = None
    archived:      bool = False

    def record(self, stage: PipelineStage, result: str,
               detail: str = "", timestamp: Optional[float] = None) -> None:
        ts = timestamp or time.time()

        # I17: timestamps must be non-decreasing within a session
        # Detects clock errors and tampering (DeepSeek audit, May 2026)
        if self.stages:
            last_ts = self.stages[-1].get("timestamp", 0.0)
            if ts < last_ts - 0.001:  # 1ms tolerance for float precision
                raise ValueError(
                    f"I17 VIOLATION: timestamp regression detected. "
                    f"Stage {stage.value} timestamp {ts:.6f} < "
                    f"previous {last_ts:.6f}. "
                    f"Clock error or tampering suspected."
                )

        if (self.stages and
                stage not in (PipelineStage.FEEDBACK, PipelineStage.FAILOVER_ENTRY)):
            last = self.stages[-1]["stage"]
            try:
                last_s = PipelineStage(last)
                if last_s.order > 0 and stage.order > 0 and stage.order < last_s.order:
                    raise ValueError(
                        f"Stage ordering violation: cannot record {stage.value} "
                        f"after {last_s.value}"
                    )
            except ValueError as e:
                if "ordering violation" in str(e):
                    raise

        self._logical_sequence += 1
        self.stages.append({
            "stage":            stage.value,
            "result":           result,
            "detail":           detail,
            "timestamp":        ts,
            "logical_sequence": self._logical_sequence,  # GAP 12: causal ordering
        })

        passed = result in ("PASS", "ALLOW", "EXECUTE")

        if stage == PipelineStage.LABELING and passed:
            if self.labeling_complete is None:
                self.labeling_complete = ts
        elif stage == PipelineStage.ARCHIVE and passed:
            if self.archive_complete is None:
                self.archive_complete = ts
        elif stage == PipelineStage.PROMOTION and passed:
            if self.promotion_complete is None:
                self.promotion_complete = ts
        elif stage == PipelineStage.REALITY_GATE and passed:
            if self._cgir_entered == 0.0 and self.reality_gate_pre_cgir is None:
                self.reality_gate_pre_cgir = ts
        elif stage == PipelineStage.CGIR:
            if self._cgir_entered == 0.0:
                self._cgir_entered = ts
        elif stage == PipelineStage.LEDGER and passed:
            if self.execution_logged is None:
                self.execution_logged = ts
        elif stage == PipelineStage.REPLAY and passed:
            if self.replay_completed is None:
                self.replay_completed = ts

    def ordering_violations(self) -> List[str]:
        """Prove timestamp ordering. Empty = correct."""
        violations = []

        def check(a_val, a_name, b_val, b_name):
            if a_val is not None and b_val is not None and a_val >= b_val:
                violations.append(
                    f"ORDERING: {a_name}({a_val:.6f}) must precede "
                    f"{b_name}({b_val:.6f})"
                )

        if self.labeling_required:
            check(self.labeling_complete, "LABELING",
                  self.archive_complete,  "ARCHIVE")
        check(self.archive_complete,    "ARCHIVE",
              self.promotion_complete,  "PROMOTION")
        check(self.promotion_complete,  "PROMOTION",
              self.reality_gate_pre_cgir, "REALITY_GATE")

        if self._cgir_entered > 0.0 and self.reality_gate_pre_cgir is not None:
            if self.reality_gate_pre_cgir >= self._cgir_entered:
                violations.append(
                    f"I5 ORDERING: REALITY_GATE({self.reality_gate_pre_cgir:.6f}) "
                    f"must precede CGIR({self._cgir_entered:.6f})"
                )
        return violations

    def assert_can_enter_cgir(self) -> None:
        """
        FATAL — call before any CGIR processing.
        Raises SystemError (hard stop) on any violation.

        labeling_required=False: labeling check skipped.
        ARCHIVE + PROMOTION + GATE: always required regardless.
        """
        failures = []
        if self.labeling_required and self.labeling_complete is None:
            failures.append("I1 VIOLATED: LABELING required but not complete")
        elif not self.labeling_required:
            # GAP 10 FIX: Orthogonal channel check (XOR gate pattern, May 2026)
            # When labeling_required=False (Option B bypass), the trace must have used
            # EITHER the LABELING stage (explicit label despite Option B) OR the
            # FAILOVER_ENTRY stage with an exception token (the documented bypass path).
            # A proposal that used neither path is an undocumented bypass — blocked.
            has_labeling  = self.labeling_complete is not None
            has_failover  = any(
                s.get("stage") == PipelineStage.FAILOVER_ENTRY.value
                for s in self.stages
            )
            if not has_labeling and not has_failover:
                failures.append(
                    "GAP 10 / I1 VIOLATED: labeling_required=False but neither "
                    "LABELING stage nor FAILOVER_ENTRY stage was recorded. "
                    "Proposal used an undocumented bypass path. "
                    "Use PipelineStage.FAILOVER_ENTRY with a valid ExceptionToken."
                )
        if self.archive_complete is None:
            failures.append("I10 VIOLATED: ARCHIVE not complete")
        if self.promotion_complete is None:
            failures.append("I3 VIOLATED: PROMOTION not complete")
        if self.reality_gate_pre_cgir is None:
            failures.append("I4+I5 VIOLATED: REALITY_GATE not passed before CGIR")
        failures.extend(self.ordering_violations())
        if failures:
            raise SystemError(
                f"PIPELINE VIOLATION — '{self.input_id}' cannot enter CGIR.\n"
                + "\n".join(f"  {f}" for f in failures)
            )

    def validate_mandatory_stages(self) -> List[str]:
        violations = []
        if self.labeling_required and self.labeling_complete is None:
            violations.append(f"I1 VIOLATED: LABELING not complete for '{self.input_id}'")
        if self.archive_complete is None:
            violations.append(f"I10 VIOLATED: ARCHIVE not complete for '{self.input_id}'")
        if self.promotion_complete is None:
            violations.append(f"I3 VIOLATED: PROMOTION not complete for '{self.input_id}'")
        if self._cgir_entered > 0.0 and self.reality_gate_pre_cgir is None:
            violations.append(
                f"I4+I5 VIOLATED: CGIR entered without REALITY_GATE "
                f"for '{self.input_id}'"
            )
        if (self.execution_logged is None and self._cgir_entered > 0.0
                and self.replay_completed is not None):
            violations.append(f"I8 VIOLATED: execution not logged for '{self.input_id}'")
        violations.extend(self.ordering_violations())
        return violations

    def passed(self, stage: PipelineStage) -> bool:
        for s in self.stages:
            if s["stage"] == stage.value and s["result"] in ("PASS","ALLOW","EXECUTE"):
                return True
        return False

    def timestamp_summary(self) -> Dict[str, Any]:
        return {
            "labeling_required":     self.labeling_required,
            "labeling_complete":     self.labeling_complete,
            "archive_complete":      self.archive_complete,
            "promotion_complete":    self.promotion_complete,
            "reality_gate_pre_cgir": self.reality_gate_pre_cgir,
            "cgir_entered":          self._cgir_entered or None,
            "execution_logged":      self.execution_logged,
            "replay_completed":      self.replay_completed,
        }

    def boolean_summary(self) -> Dict[str, bool]:
        """Backward compat — booleans derived from timestamps."""
        return {
            "labeling_complete":     self.labeling_complete is not None,
            "archive_complete":      self.archive_complete is not None,
            "promotion_complete":    self.promotion_complete is not None,
            "reality_gate_pre_cgir": self.reality_gate_pre_cgir is not None,
            "execution_logged":      self.execution_logged is not None,
            "replay_completed":      self.replay_completed is not None,
        }

    def to_dict(self) -> Dict[str, Any]:
        violations = self.validate_mandatory_stages()
        return {
            "input_id":          self.input_id,
            "labeling_required": self.labeling_required,
            "timestamps":        self.timestamp_summary(),
            "booleans":          self.boolean_summary(),
            "stages":            self.stages,
            "rejected_at":       self.rejected_at,
            "archived":          self.archived,
            "compliant":         len(violations) == 0,
            "violations":        violations,
        }

    @property
    def trace_hash(self) -> str:
        # binding: @LabyrinthCoder
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",",":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class FeedbackRecord:
    input_id:     str
    outcome:      str
    stage_failed: Optional[str]
    reason:       str
    trace_hash:   str
    archived_at:  float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_id":     self.input_id,
            "outcome":      self.outcome,
            "stage_failed": self.stage_failed,
            "reason":       self.reason,
            "trace_hash":   self.trace_hash,
            "archived_at":  self.archived_at,
        }


def validate_trace(trace: PipelineTrace) -> List[str]:
    return trace.validate_mandatory_stages()


def create_feedback(trace: PipelineTrace, outcome: str,
                    reason: str = "") -> FeedbackRecord:
    stage_failed = None
    if outcome in ("BLOCKED","REJECTED","DEFERRED"):
        for s in reversed(trace.stages):
            if s["result"] in ("BLOCK","FAIL","REJECT","DEFER"):
                stage_failed = s["stage"]
                break
    return FeedbackRecord(
        input_id=trace.input_id, outcome=outcome,
        stage_failed=stage_failed, reason=reason or outcome,
        trace_hash=trace.trace_hash,
    )


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_compliant(input_id="compliant", labeling_required=True) -> PipelineTrace:
    t = PipelineTrace(input_id=input_id, labeling_required=labeling_required)
    if labeling_required:
        t.record(PipelineStage.INPUT,    "PASS", timestamp=1.0)
        t.record(PipelineStage.LABELING, "PASS", timestamp=2.0)
    else:
        t.record(PipelineStage.FAILOVER_ENTRY, "PASS", "Option B", timestamp=1.0)
        t.record(PipelineStage.INPUT,          "PASS", timestamp=1.1)
    t.record(PipelineStage.ARCHIVE,      "PASS", timestamp=3.0)
    t.record(PipelineStage.PROMOTION,    "PASS", timestamp=4.0)
    t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=5.0)
    t.record(PipelineStage.CGIR,         "PASS", timestamp=6.0)
    t.record(PipelineStage.GATE,         "PASS", timestamp=7.0)
    t.record(PipelineStage.AEGIS,        "PASS", timestamp=8.0)
    t.record(PipelineStage.LEDGER,       "PASS", timestamp=9.0)
    t.record(PipelineStage.REPLAY,       "PASS", timestamp=10.0)
    return t



def pipeline_mass_snapshot(
    trace: "PipelineTrace",
    stage_name: str,
    confidence: float,
    proposal_count: int = 1,
) -> dict:
    """
    Record a PIPELINE_MASS telemetry snapshot for a stage transition.

    Logs confidence×count (epistemic mass) at this stage. Over time,
    these snapshots make healing and promotion dynamics visible to operators
    — showing where proposals accumulate (pressure buildup) or leak (low-
    confidence fallthrough).

    Based on mass telemetry pattern (May 2026):
    every trial measures mass in specific spatial zones at specific
    generations. Same principle applied to pipeline stages.

    Returns a dict suitable for logging to the chronicle.
    """
    return {
        "stage":           stage_name,
        "epistemic_mass":  round(confidence * proposal_count, 6),
        "confidence":      round(confidence, 6),
        "proposal_count":  proposal_count,
        "trace_input_id":  getattr(trace, "input_id", "unknown"),
        "kind":            "PIPELINE_MASS",
    }


def _test_timestamps_set_on_pass() -> bool:
    t = PipelineTrace(input_id="ts1")
    assert t.labeling_complete is None
    t.record(PipelineStage.LABELING, "PASS")
    assert isinstance(t.labeling_complete, float) and t.labeling_complete > 0
    return True

def _test_timestamps_not_set_on_fail() -> bool:
    t = PipelineTrace(input_id="ts2")
    t.record(PipelineStage.LABELING, "FAIL")
    assert t.labeling_complete is None
    return True

def _test_all_six_timestamp_fields_default_none() -> bool:
    t = PipelineTrace(input_id="ts3")
    for f in ["labeling_complete","archive_complete","promotion_complete",
              "reality_gate_pre_cgir","execution_logged","replay_completed"]:
        assert getattr(t, f) is None
    return True

def _test_ordering_proof_correct() -> bool:
    t = _make_compliant()
    assert len(t.ordering_violations()) == 0
    # Verify timestamps are strictly ordered
    assert t.labeling_complete < t.archive_complete
    assert t.archive_complete < t.promotion_complete
    assert t.promotion_complete < t.reality_gate_pre_cgir
    assert t.reality_gate_pre_cgir < t._cgir_entered
    return True

def _test_i5_gate_after_cgir_detected() -> bool:
    """
    I4+I5: REALITY_GATE must precede CGIR. Recording REALITY_GATE after
    CGIR should be detected — either by ordering guard raising or
    by validate_mandatory_stages() reporting the violation.
    """
    t = PipelineTrace(input_id="i5v")
    t.record(PipelineStage.INPUT,     "PASS", timestamp=1.0)
    t.record(PipelineStage.LABELING,  "PASS", timestamp=2.0)
    t.record(PipelineStage.ARCHIVE,   "PASS", timestamp=3.0)
    t.record(PipelineStage.PROMOTION, "PASS", timestamp=4.0)
    t.record(PipelineStage.CGIR,      "PASS", timestamp=5.0)
    # REALITY_GATE after CGIR: ordering guard may raise, or violation is logged
    try:
        t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=6.0)
        # If no raise: reality_gate_pre_cgir must be None (gate not pre-CGIR)
        # and validate must report the violation
        assert t.reality_gate_pre_cgir is None
        violations = t.validate_mandatory_stages()
        assert any("I4" in v or "I5" in v or "REALITY_GATE" in v for v in violations), (
            f"Expected I4+I5 violation, got: {violations}"
        )
    except (ValueError, SystemError) as e:
        # Ordering guard fired — this IS detection of the I4+I5 violation
        assert any(kw in str(e) for kw in ("REALITY_GATE", "I4", "I5", "ordering")), (
            f"Unexpected error: {e}"
        )
    return True

def _test_labeling_required_true_blocks_without_labeling() -> bool:
    t = PipelineTrace(input_id="lr1", labeling_required=True)
    t.record(PipelineStage.ARCHIVE, "PASS", timestamp=3.0)
    t.record(PipelineStage.PROMOTION, "PASS", timestamp=4.0)
    t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=5.0)
    try:
        t.assert_can_enter_cgir()
        raise AssertionError("Should raise")
    except SystemError as e:
        assert "I1" in str(e)
    return True

def _test_labeling_required_false_skips_labeling_check() -> bool:
    t = PipelineTrace(input_id="lr2", labeling_required=False)
    t.record(PipelineStage.FAILOVER_ENTRY, "PASS", timestamp=1.0)
    t.record(PipelineStage.INPUT, "PASS", timestamp=1.1)
    t.record(PipelineStage.ARCHIVE, "PASS", timestamp=3.0)
    t.record(PipelineStage.PROMOTION, "PASS", timestamp=4.0)
    t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=5.0)
    t.assert_can_enter_cgir()  # must not raise
    return True

def _test_option_b_still_needs_archive_promotion_gate() -> bool:
    t = PipelineTrace(input_id="optb", labeling_required=False)
    t.record(PipelineStage.FAILOVER_ENTRY, "PASS")
    try:
        t.assert_can_enter_cgir()
        raise AssertionError("Should raise")
    except SystemError as e:
        assert "I10" in str(e)
        assert "I3"  in str(e)
        assert "I4+I5" in str(e)
    return True

def _test_system_error_not_value_error() -> bool:
    t = PipelineTrace(input_id="fatal")
    try:
        t.assert_can_enter_cgir()
    except SystemError:
        pass
    except ValueError:
        raise AssertionError("Must be SystemError")
    return True

def _test_full_compliant_no_violations() -> bool:
    t = _make_compliant()
    assert len(validate_trace(t)) == 0
    ts = t.timestamp_summary()
    for k,v in ts.items():
        if k not in ("labeling_required","cgir_entered"):
            assert v is not None, f"Expected {k} to be set"
    return True

def _test_option_b_compliant() -> bool:
    t = _make_compliant(labeling_required=False)
    violations = validate_trace(t)
    assert len(violations) == 0, f"Option B violations: {violations}"
    assert t.labeling_complete is None
    assert t.archive_complete is not None
    assert t.promotion_complete is not None
    assert t.reality_gate_pre_cgir is not None
    return True

def _test_boolean_summary_backward_compat() -> bool:
    t = _make_compliant()
    bs = t.boolean_summary()
    assert len(bs) == 6
    assert all(isinstance(v, bool) for v in bs.values())
    assert all(v for v in bs.values())
    return True

def _test_feedback_created() -> bool:
    t = PipelineTrace(input_id="fb1")
    t.record(PipelineStage.INPUT, "PASS")
    fb = create_feedback(t, "REJECTED", "test")
    assert fb.outcome == "REJECTED" and len(fb.trace_hash) == 64
    return True

def _test_failover_accepted() -> bool:
    t = PipelineTrace(input_id="fo1", labeling_required=False)
    t.record(PipelineStage.FAILOVER_ENTRY, "PASS")
    t.record(PipelineStage.INPUT, "PASS")
    assert t.labeling_complete is None
    return True


def _test_gap10_option_b_with_failover_entry_passes() -> bool:
    """GAP 10: Option B with FAILOVER_ENTRY stage should pass assert_can_enter_cgir."""
    import time
    t = PipelineTrace(input_id="gap10_ok", labeling_required=False)
    ts = time.time()
    t.record(PipelineStage.INPUT,        "PASS", timestamp=ts + 0.001)
    t.record(PipelineStage.FAILOVER_ENTRY, "PASS", "ExceptionToken:prototype", timestamp=ts + 0.002)
    t.record(PipelineStage.ARCHIVE,      "PASS", timestamp=ts + 0.003)
    t.record(PipelineStage.PROMOTION,    "PASS", timestamp=ts + 0.004)
    t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=ts + 0.005)
    t.assert_can_enter_cgir()  # must not raise
    return True


def _test_gap10_option_b_with_labeling_also_passes() -> bool:
    """GAP 10: Option B with explicit LABELING stage also allowed."""
    import time
    t = PipelineTrace(input_id="gap10_label", labeling_required=False)
    ts = time.time()
    t.record(PipelineStage.INPUT,        "PASS", timestamp=ts + 0.001)
    t.record(PipelineStage.LABELING,     "PASS", timestamp=ts + 0.002)
    t.record(PipelineStage.ARCHIVE,      "PASS", timestamp=ts + 0.003)
    t.record(PipelineStage.PROMOTION,    "PASS", timestamp=ts + 0.004)
    t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=ts + 0.005)
    t.assert_can_enter_cgir()  # must not raise
    return True


def _test_gap10_option_b_without_either_blocked() -> bool:
    """GAP 10: Option B with NEITHER LABELING nor FAILOVER_ENTRY must be blocked."""
    import time
    t = PipelineTrace(input_id="gap10_bad", labeling_required=False)
    ts = time.time()
    t.record(PipelineStage.INPUT,        "PASS", timestamp=ts + 0.001)
    t.record(PipelineStage.ARCHIVE,      "PASS", timestamp=ts + 0.002)
    t.record(PipelineStage.PROMOTION,    "PASS", timestamp=ts + 0.003)
    t.record(PipelineStage.REALITY_GATE, "PASS", timestamp=ts + 0.004)
    try:
        t.assert_can_enter_cgir()
        return False  # should have raised
    except SystemError as e:
        return "GAP 10" in str(e) or "undocumented bypass" in str(e).lower()


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


if __name__ == "__main__":
    print("=" * 70)
    print("PIPELINE WIRE — Labyrinth-OS")
    print("Timestamps. labeling_required. Ordering proof. Fatal on violation.")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed: raise SystemExit(1)
    import hashlib as _hl
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}")
    print(f"\n{'='*70}\n  PIPELINE WIRE — COMPLETE\n{'='*70}")
