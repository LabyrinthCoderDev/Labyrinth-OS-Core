from __future__ import annotations
import math
"""
cgir_guardian_bridge.py — Labyrinth-OS / L10→L12 Bridge
=========================================================
CGIR → Guardian Slot Bridge

Translates between the formal CGIR execution layer (L10/L11) and the
operational Guardian Slot engine (L12).

The bridge has two directions:

  FORWARD (sensors → CGIR → Guardian):
    SensorReadings → CGIRGraph (with CouncilSignal) → AEGISCycle
    → CycleResult → GuardianSignal → GuardianSlot.evaluate()

  The CycleResult from AEGIS contains the Gate decision (ALLOW/BLOCK)
  and the SignalNode severity/confidence. The bridge extracts these
  and compiles them into a GuardianSignal that guardian_slot understands.

Why this bridge exists:
  CGIR is the formal layer — it proves things.
  Guardian Slot is the operational gate — it acts.
  They speak different types. This module is the translation.

Rules:
  - CGIR BLOCK always maps to GuardianSlot BLOCK or KILL.
  - CGIR ALLOW does not guarantee GuardianSlot EXECUTE —
    guardian_slot can still BLOCK on confidence or other checks.
  - CRITICAL severity from CGIR maps to KILL intent.
  - Translation is deterministic: same CycleResult → same GuardianSignal.
  - No state. No side effects. Pure translation.

References:
  ARCHITECTURE.md  — L10 CGIR, L11 Gate, L12 AEGIS/CESK
  cgir_signal_algebra.py — SensorReadings type
  aegis_cesk.py          — CycleResult type
  guardian_slot.py       — GuardianSignal, SlotDecision
"""


import hashlib
import sys
import time
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from cgir_types import GateDecision, Severity
from cgir_signal_algebra import SensorReadings, evaluate as _signal_eval, TAU_FLOOR, CHI_COL
from aegis_cesk import CycleResult, AEGISKernel
from watcher_a import WatcherA
from watcher_b import WatcherB
from council_resolver import CouncilResolver
from cgir_types import Edge, Node, NodeType, TimeRange
from cgir_core import CGIRGraph
from guardian_slot import GuardianSignal, GuardianSlot, SlotDecision, SlotResult


# ─── BRIDGE RESULT ────────────────────────────────────────────────────────────

@dataclass
class BridgeResult:
    """
    Output of one full bridge evaluation.

    cycle_result     — AEGIS cycle result (formal layer)
    guardian_signal  — translated input for guardian_slot
    slot_result      — guardian_slot decision
    bridge_hash      — SHA-256 of (cycle graph_hash + slot receipt_hash)
    """
    cycle_result: CycleResult
    guardian_signal: GuardianSignal
    slot_result: SlotResult
    bridge_hash: str

    @property
    def final_decision(self) -> SlotDecision:
        return self.slot_result.decision

    @property
    def is_safe_to_execute(self) -> bool:
        return self.slot_result.decision == SlotDecision.EXECUTE

    def to_dict(self):
        return {
            "cycle_decision":  self.cycle_result.decision.value,
            "gate_blocked_at": self.cycle_result.blocked_at,
            "slot_decision":   self.slot_result.decision.value,
            "slot_reasons":    [r.value for r in self.slot_result.reasons],
            "bridge_hash":     self.bridge_hash,
            "is_safe":         self.is_safe_to_execute,
        }


# ─── TRANSLATOR ───────────────────────────────────────────────────────────────

class CGIRGuardianBridge:
    """
    Translates CGIR CycleResult → GuardianSignal → SlotResult.

    Two entry points:

    1. from_cycle_result(cycle, readings, cbf_margin, action_id)
       — Takes a pre-run AEGIS cycle and sensor readings.
       — Extracts confidence and severity from cycle.
       — Runs guardian_slot.evaluate().

    2. run(proposal, readings, cbf_margin, session_id, action_id)
       — Builds and runs the full CGIR pipeline from a proposal dict.
       — Then translates to guardian_slot.
       — Single-call end-to-end evaluation.
    """

    def __init__(self) -> None:
        self._kernel   = AEGISKernel()
        self._guardian = GuardianSlot()

    # ── Translation: CycleResult → GuardianSignal ─────────────────────────────

    @staticmethod
    def translate(
        cycle: CycleResult,
        readings: SensorReadings,
        cbf_margin: float = 0.5,
        action_id: str = "",
        human_override: Optional[str] = None,
    ) -> GuardianSignal:
        """
        Translate a CycleResult + SensorReadings into a GuardianSignal.

        Confidence mapping:
          - If CGIR blocked → confidence is clipped to 0.5 max (forces BLOCK)
          - If CGIR allowed → use readings confidence as-is
          - If CRITICAL signal in cycle → use 0.0 (forces KILL in guardian)

        chi_vector: guardian_slot uses a scalar chi, not a vector.
          We use the max of the chi_vector (most conservative).
        """
        # Extract severity from gate result
        cycle_blocked  = cycle.decision == GateDecision.BLOCK
        has_critical   = False
        signal_conf    = readings.confidence

        if cycle.gate_result is not None and cycle_blocked:
            # Check if the block was due to CRITICAL (vs ERROR)
            # FRAGILE: string matching on human-readable reason string.
            # ROADMAP: use cycle.gate_result.block_reason (BlockReason enum) instead.
            # Tracked as GPT audit finding #4 — replace once GateResult.block_reason
            # is populated by cgir_gate.evaluate().
            reason = cycle.gate_result.reason or ""
            has_critical = cycle_blocked and "CRITICAL" in reason and "No CRITICAL" not in reason

        # Confidence: clamp down if CGIR blocked it
        if has_critical:
            guardian_conf = 0.0           # critical → guardian KILL path
        elif cycle_blocked:
            guardian_conf = min(signal_conf, 0.50)  # ensures BLOCK in guardian
        else:
            guardian_conf = signal_conf

        # chi scalar: hybrid hard-threshold + resonance sensitivity
        #
        # Layer 1 (constitutional floor — Z3 proven):
        #   max() preserves the existing hard threshold guarantee.
        #   any(x >= CHI_COLLAPSE) → KILL is still enforced in guardian slot.
        #
        # Layer 2 (aggregate detection — chi vulnerability correction, May 2026):
        #   mean() catches vectors like [0.39, 0.39] where no single component
        #   breaches CHI_COLLAPSE but aggregate contradiction density is at ceiling.
        #   CHI_AGGREGATE_FLOOR = 0.28 — if mean exceeds this, treat as collapsed.
        #   Derivation: CHI_COLLAPSE * 0.70 = 0.40 * 0.70 = 0.28. Two components
        #   both at 0.70× collapse threshold constitute a structural violation.
        #
        # Layer 3 (resonance sensitivity — Poole Manifold pattern):
        #   Distance from ideal chi peaks [0.05, 0.15] produces resonance.
        #   Resonance < 0.05 means chi is far from any healthy state.
        #   Applied as a confidence penalty rather than a hard KILL to preserve
        #   Z3-proven threshold primacy.
        #
        # Result: chi_scalar is the worst-case reading that downstream
        # guardian_slot uses for its hard threshold checks (Layer 1).
        # Layers 2 and 3 fire earlier, before guardian_slot sees the signal.

        CHI_AGGREGATE_FLOOR = 0.28  # 70% of CHI_COLLAPSE — aggregate trigger

        if readings.chi_vector:
            chi_max  = max(readings.chi_vector)
            chi_mean = sum(readings.chi_vector) / len(readings.chi_vector)

            # Layer 2: aggregate check — escalate chi_scalar if mean is dangerous
            # This catches [0.39, 0.39] which max() alone would report as 0.39
            if chi_mean >= CHI_AGGREGATE_FLOOR:
                # Elevate chi_scalar to CHI_COLLAPSE to trigger KILL in guardian
                # The aggregate is as dangerous as a single component at collapse
                chi_scalar = max(chi_max, 0.40)  # force past CHI_COLLAPSE floor
            else:
                chi_scalar = chi_max

            # Layer 3: resonance sensitivity — Poole Manifold contribution
            # Ideal chi peaks: low contradiction density [0.05, 0.15]
            # If chi is far from ideal, reduce confidence to signal elevated risk
            _chi_peaks   = [0.05, 0.15]
            _alpha        = 0.35
            _sigma_sq     = 0.01
            _chi_resonance = sum(
                _alpha * math.exp(-(chi_mean - p) ** 2 / _sigma_sq)
                for p in _chi_peaks
            )
            # Resonance < 0.05 → chi is far from any healthy state
            # Apply confidence penalty (does not override Layer 1 hard threshold)
            if _chi_resonance < 0.05 and not has_critical:
                # Dampen confidence to ensure guardian slot sees the risk
                guardian_conf = min(guardian_conf, 0.45)
        else:
            chi_scalar = 0.0

        return GuardianSignal(
            tau_escape      = readings.tau_escape,
            drift_score     = readings.drift_score,
            chi_vector      = chi_scalar,
            cbf_margin      = cbf_margin,
            betti_1         = readings.betti_1,
            confidence      = guardian_conf,
            action_id       = action_id,
            human_override  = human_override,
        )

    # ── from_cycle_result ─────────────────────────────────────────────────────

    def from_cycle_result(
        self,
        cycle: CycleResult,
        readings: SensorReadings,
        cbf_margin: float = 0.5,
        action_id: str = "",
        human_override: Optional[str] = None,
    ) -> BridgeResult:
        """Translate an existing CycleResult into a BridgeResult."""
        g_signal = self.translate(
            cycle, readings, cbf_margin, action_id, human_override
        )
        slot_result = self._guardian.evaluate(g_signal)
        bridge_hash = hashlib.sha256(
            (cycle.graph_hash + slot_result.receipt_hash).encode()
        ).hexdigest()
        return BridgeResult(
            cycle_result    = cycle,
            guardian_signal = g_signal,
            slot_result     = slot_result,
            bridge_hash     = bridge_hash,
        )

    # ── run: full pipeline ────────────────────────────────────────────────────

    def run(
        self,
        proposal: dict,
        readings: SensorReadings,
        cbf_margin: float = 0.5,
        session_id: Optional[str] = None,
        action_id: str = "",
        human_override: Optional[str] = None,
    ) -> BridgeResult:
        """
        Full pipeline: proposal → CGIR → GuardianSlot.

        Steps:
          1. Run AEGIS cycle on proposal (formal validation + gate)
          2. Translate CycleResult + readings → GuardianSignal
          3. Run GuardianSlot.evaluate()
          4. Return BridgeResult
        """
        cycle = self._kernel.run_cycle(proposal, session_id)
        return self.from_cycle_result(
            cycle, readings, cbf_margin, action_id, human_override
        )


# ─── PROPOSAL BUILDER ─────────────────────────────────────────────────────────

def build_proposal_from_readings(
    readings: SensorReadings,
    action_id: str = "",
    session_id: str = "",
) -> dict:
    """
    Build a minimal CGIR proposal dict from sensor readings.
    Runs Watcher-A and Watcher-B and attaches a council signal.

    This is what the Planner would normally do — here it's a
    minimal stub that constructs a two-node graph from sensor data.
    """
    # Build a minimal graph representing this inference step
    graph = CGIRGraph()
    graph.add_node(Node(
        id=f"state_{session_id}_0",
        node_type=NodeType.STATE,
        logical_time=readings.logical_time,
        metadata={"action_id": action_id, "source": readings.source},
    ))
    graph.add_node(Node(
        id=f"state_{session_id}_1",
        node_type=NodeType.STATE,
        logical_time=readings.logical_time + 1,
        metadata={"action_id": action_id},
    ))
    graph.add_edge(Edge(
        id=f"step_{session_id}_0",
        from_id=f"state_{session_id}_0",
        to_id=f"state_{session_id}_1",
        event_type="INFERENCE_STEP",
        invariant_mask=["I1", "I3", "I7"],
        signal_binding=f"council_sig_{session_id}",
    ))
    graph.set_root(f"state_{session_id}_0")
    graph.set_tip(f"state_{session_id}_1")

    # Run watchers and council
    ra = WatcherA().audit(graph)
    rb = WatcherB().audit(graph)
    sig_node = _signal_eval(readings, f"pre_council_{session_id}")
    council = CouncilResolver().resolve(
        ra, rb,
        signal_id=f"council_sig_{session_id}",
        logical_time=readings.logical_time,
        valid_for=TimeRange(
            start_time=readings.logical_time,
            end_time=readings.logical_time + 1,
        ),
        sensor_severity=sig_node.severity,
        sensor_confidence=sig_node.confidence,
    )

    # Serialize council signal into proposal
    vf = None
    if council.signal.valid_for:
        vf = {
            "start_time": council.signal.valid_for.start_time,
            "end_time":   council.signal.valid_for.end_time,
        }

    return {
        "nodes": [
            {"id": f"state_{session_id}_0", "node_type": "STATE",
             "logical_time": readings.logical_time,
             "metadata": {"action_id": action_id}},
            {"id": f"state_{session_id}_1", "node_type": "STATE",
             "logical_time": readings.logical_time + 1,
             "metadata": {"action_id": action_id}},
        ],
        "edges": [{
            "id": f"step_{session_id}_0",
            "from_id": f"state_{session_id}_0",
            "to_id":   f"state_{session_id}_1",
            "event_type": "INFERENCE_STEP",
            "invariant_mask": ["I1", "I3", "I7"],
            "signal_binding": f"council_sig_{session_id}",
        }],
        "signals": [{
            "id":          council.signal.id,
            "logical_time": council.signal.logical_time,
            "severity":    council.signal.severity.value,
            "confidence":  council.signal.confidence,
            "category":    council.signal.category,
            "source":      council.signal.source,
            "emitted_by":  council.signal.emitted_by,
            "valid_for":   vf,
        }],
        "root": f"state_{session_id}_0",
        "tip":  f"state_{session_id}_1",
    }


# ─── CONVENIENCE ──────────────────────────────────────────────────────────────

def evaluate(
    readings: SensorReadings,
    cbf_margin: float = 0.5,
    action_id: str = "",
    session_id: Optional[str] = None,
    human_override: Optional[str] = None,
) -> BridgeResult:
    """
    Single-call evaluation: SensorReadings → BridgeResult.

    This is the primary entry point for the operational pipeline.
    Builds proposal, runs CGIR, runs guardian_slot.
    """
    sid = session_id or f"bridge_{int(time.time())}"
    bridge = CGIRGuardianBridge()
    proposal = build_proposal_from_readings(readings, action_id, sid)
    return bridge.run(
        proposal, readings, cbf_margin,
        session_id=sid, action_id=action_id,
        human_override=human_override,
    )


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _nominal() -> SensorReadings:
    return SensorReadings(
        tau_escape=0.90, drift_score=0.05,
        chi_vector=[0.06, 0.08], betti_1=0.01,
        confidence=0.88, source="VECTOR", logical_time=0,
    )

def _critical() -> SensorReadings:
    return SensorReadings(
        tau_escape=0.40, drift_score=0.20,
        chi_vector=[0.50], betti_1=0.06,
        confidence=0.30, source="VECTOR", logical_time=0,
    )


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_nominal_executes() -> bool:
    result = evaluate(_nominal(), cbf_margin=0.6, action_id="act_001", session_id="t_nom")
    assert isinstance(result, BridgeResult)
    assert result.slot_result.decision == SlotDecision.EXECUTE, (
        f"Expected EXECUTE, got {result.slot_result.decision.value} "
        f"reasons={[r.value for r in result.slot_result.reasons]}"
    )
    return True

def _test_critical_kills() -> bool:
    result = evaluate(_critical(), cbf_margin=0.3, session_id="t_crit")
    assert result.slot_result.decision in (SlotDecision.KILL, SlotDecision.BLOCK)
    return True

def _test_bridge_hash_is_64_hex() -> bool:
    result = evaluate(_nominal(), session_id="t_hash")
    assert len(result.bridge_hash) == 64
    assert all(c in "0123456789abcdef" for c in result.bridge_hash)
    return True

def _test_cycle_result_present() -> bool:
    result = evaluate(_nominal(), session_id="t_cycle")
    assert result.cycle_result is not None
    assert isinstance(result.cycle_result, CycleResult)
    return True

def _test_guardian_signal_present() -> bool:
    result = evaluate(_nominal(), session_id="t_gsig")
    assert result.guardian_signal is not None
    assert isinstance(result.guardian_signal, GuardianSignal)
    return True

def _test_to_dict_has_keys() -> bool:
    result = evaluate(_nominal(), session_id="t_dict")
    d = result.to_dict()
    for k in ["cycle_decision","slot_decision","bridge_hash","is_safe"]:
        assert k in d, f"Missing key: {k}"
    return True

def _test_human_kill_overrides() -> bool:
    """Human KILL override produces KILL regardless of sensor state."""
    result = evaluate(_nominal(), session_id="t_hkill",
                      human_override="KILL")
    assert result.slot_result.decision == SlotDecision.KILL
    return True

def _test_cgir_block_clips_confidence() -> bool:
    """When CGIR blocks, confidence is clipped → guardian also blocks/kills."""
    # Use readings that CGIR will block (tau too low → CRITICAL signal)
    result = evaluate(_critical(), session_id="t_clip")
    # guardian should not EXECUTE on a blocked CGIR cycle
    assert result.slot_result.decision != SlotDecision.EXECUTE
    return True

def _test_same_readings_same_result() -> bool:
    """Same inputs → same final decision (deterministic)."""
    r1 = evaluate(_nominal(), cbf_margin=0.6, session_id="det_1")
    r2 = evaluate(_nominal(), cbf_margin=0.6, session_id="det_2")
    assert r1.slot_result.decision == r2.slot_result.decision
    return True

def _test_translate_static() -> bool:
    """translate() static method works independently."""
    from aegis_cesk import run_cycle
    from cgir_signal_algebra import SensorReadings
    readings = _nominal()
    proposal = build_proposal_from_readings(readings, "act", "static_test")
    cycle = run_cycle(proposal, "static_test")
    g_sig = CGIRGuardianBridge.translate(cycle, readings, cbf_margin=0.6)
    assert isinstance(g_sig, GuardianSignal)
    return True

def _test_is_safe_true_for_nominal() -> bool:
    result = evaluate(_nominal(), cbf_margin=0.6, session_id="t_safe")
    assert result.is_safe_to_execute is True
    return True

def _test_is_safe_false_for_critical() -> bool:
    result = evaluate(_critical(), session_id="t_unsafe")
    assert result.is_safe_to_execute is False
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
    print("CGIR GUARDIAN BRIDGE — Labyrinth-OS L10→L12")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        raise SystemExit(1)

    # Demo
    print("\n── DEMO: Sensor → CGIR → Guardian ──\n")
    scenarios = [
        ("NOMINAL",   _nominal(),   0.6),
        ("CRITICAL",  _critical(),  0.3),
        ("HUMAN_KILL",_nominal(),   0.6),
    ]
    for label, r, cbf in scenarios:
        override = "KILL" if label == "HUMAN_KILL" else None
        res = evaluate(r, cbf_margin=cbf, session_id=f"demo_{label}",
                       human_override=override)
        print(f"  {label:12} CGIR={res.cycle_result.decision.value:5}  "
              f"GATE={res.slot_result.decision.value:7}  "
              f"safe={res.is_safe_to_execute}")

    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}")
    print(f"\n{'=' * 70}")
    print(f"  CGIR GUARDIAN BRIDGE — COMPLETE")
    print(f"{'=' * 70}")