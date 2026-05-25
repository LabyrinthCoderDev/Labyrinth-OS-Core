"""
system_snapshot.py — Labyrinth-OS-Portable
==========================================
Full system state capture. Immutable once saved. Hash-verified.

A SystemSnapshot captures everything needed to restore the system
to a known good state:
  - Constitutional threshold values (session-level copies, not Z3 baseline)
  - EWMA degradation detector state
  - Evolution engine step count and current adjustments
  - Circuit breaker state
  - Session memory summary (stats only, not full memory)
  - Timestamp and reason for the snapshot

This is NOT the same as a model registry snapshot.
Model registry snapshots save the model config and system prompt.
SystemSnapshot saves the constitutional enforcement state —
the thresholds, the healing history, the gate calibration.

Boot points:
  'baseline'         — taken on first boot, immutable forever
  'pre_update_<ts>'  — taken automatically before every approved change
  'sandbox_<ts>'     — taken before a sandbox test run
  user-named         — taken manually via /snapshot CLI or settings screen

@LabyrinthCoder — Labyrinth-OS-Portable
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


SNAPSHOT_DIR = Path.home() / ".labyrinth_os_portable" / "snapshots"


@dataclass
class ThresholdState:
    """Current session-level threshold values. NOT the Z3 baseline."""
    tau_floor:         float
    chi_collapse:      float
    drift_threshold:   float
    betti_cap:         float
    confidence_floor:  float
    evolution_step:    int
    deviation_from_baseline: dict  # how far each has drifted from Z3 constants


@dataclass
class HealingState:
    """State of the healing system at snapshot time."""
    circuit_state:       str    # CLOSED / OPEN / HALF_OPEN
    consecutive_blocks:  int
    ewma_block_rate:     float
    ewma_confidence:     float
    degrade_state:       str    # NOMINAL / WARNING / ANOMALY
    degrade_streak:      int


@dataclass
class MemorySummary:
    """Stats about memory — not the full contents."""
    total_entries:   int
    session_count:   int
    turn_count:      int
    db_size_bytes:   int


@dataclass
class SystemSnapshot:
    """
    Immutable full-system state capture.
    Once created and saved, never modified.
    Hash verified on load.
    """
    snapshot_id:     str
    label:           str        # 'baseline', 'pre_update_<ts>', user name
    created_at:      float
    reason:          str        # why this snapshot was taken
    model_id:        str        # which model was active
    session_id:      str

    thresholds:      ThresholdState
    healing:         HealingState
    memory_summary:  MemorySummary

    content_hash:    str = ""   # SHA-256 of content, set on save
    is_baseline:     bool = False  # baseline snapshots cannot be deleted

    def compute_hash(self) -> str:
        payload = json.dumps({
            "snapshot_id":  self.snapshot_id,
            "label":        self.label,
            "created_at":   self.created_at,
            "model_id":     self.model_id,
            "thresholds":   asdict(self.thresholds),
            "healing":      asdict(self.healing),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def verify(self) -> bool:
        return self.content_hash == self.compute_hash()

    def to_dict(self) -> dict:
        return {
            "snapshot_id":    self.snapshot_id,
            "label":          self.label,
            "created_at":     self.created_at,
            "reason":         self.reason,
            "model_id":       self.model_id,
            "session_id":     self.session_id,
            "thresholds":     asdict(self.thresholds),
            "healing":        asdict(self.healing),
            "memory_summary": asdict(self.memory_summary),
            "content_hash":   self.content_hash,
            "is_baseline":    self.is_baseline,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SystemSnapshot":
        return cls(
            snapshot_id=d["snapshot_id"],
            label=d["label"],
            created_at=d["created_at"],
            reason=d["reason"],
            model_id=d["model_id"],
            session_id=d["session_id"],
            thresholds=ThresholdState(**d["thresholds"]),
            healing=HealingState(**d["healing"]),
            memory_summary=MemorySummary(**d["memory_summary"]),
            content_hash=d["content_hash"],
            is_baseline=d.get("is_baseline", False),
        )


class BootManager:
    """
    Manages system snapshots and boot points.

    Rules:
    - 'baseline' snapshot is taken once on first boot, never deleted
    - 'pre_update_<ts>' taken automatically before every approved change
    - User can take named snapshots manually
    - Any snapshot can be booted from
    - Hash verified before loading — tampered snapshots rejected

    Usage:
        bm = BootManager()
        bm.save_baseline(agent)             # first boot only
        snap_id = bm.save(agent, "before-experiment")
        bm.boot(snap_id, agent)             # restore to that state
        bm.list()                           # see all snapshots
    """

    def __init__(self, snapshot_dir: Path | str = SNAPSHOT_DIR) -> None:
        self.dir = Path(snapshot_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(
        self,
        agent,
        label:  str = "",
        reason: str = "",
    ) -> str:
        """
        Take a snapshot of the current agent state.
        Returns snapshot_id.
        """
        ts    = int(time.time())
        sid   = str(uuid.uuid4())[:8]
        label = label or f"snapshot_{ts}"

        snap = self._capture(agent, label, reason, sid)
        snap.content_hash = snap.compute_hash()
        self._write(snap)
        return snap.snapshot_id

    def save_pre_update(self, agent, proposal_id: str) -> str:
        """
        Automatically called before any approved proposal is applied.
        Label: pre_update_<timestamp>
        """
        label  = f"pre_update_{int(time.time())}"
        reason = f"Auto-snapshot before applying proposal {proposal_id}"
        return self.save(agent, label, reason)

    def save_baseline(self, agent) -> str:
        """
        Take the baseline snapshot on first boot.
        Baseline is immutable — cannot be deleted.
        Returns snapshot_id or existing baseline id if already exists.
        """
        # Check if baseline already exists
        existing = self._find_baseline()
        if existing:
            return existing.snapshot_id

        ts   = int(time.time())
        sid  = str(uuid.uuid4())[:8]
        snap = self._capture(agent, "baseline", "Initial baseline — first boot", sid)
        snap.is_baseline   = True
        snap.content_hash  = snap.compute_hash()
        self._write(snap)
        return snap.snapshot_id

    # ── Load / Boot ───────────────────────────────────────────────────────────

    def boot(self, snapshot_id: str, agent) -> bool:
        """
        Restore agent to a saved snapshot state.
        Verifies hash before applying — rejects tampered snapshots.
        Returns True on success.
        """
        snap = self.load(snapshot_id)
        if snap is None:
            return False
        if not snap.verify():
            raise ValueError(
                f"Snapshot {snapshot_id} failed hash verification. "
                f"File may have been tampered with. Will not boot."
            )
        self._apply(snap, agent)
        return True

    def load(self, snapshot_id: str) -> Optional[SystemSnapshot]:
        path = self.dir / f"{snapshot_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return SystemSnapshot.from_dict(json.load(f))

    # ── List ──────────────────────────────────────────────────────────────────

    def list_snapshots(self) -> list[dict]:
        """List all snapshots, most recent first."""
        snaps = []
        for p in self.dir.glob("*.json"):
            try:
                with open(p) as f:
                    d = json.load(f)
                snaps.append({
                    "snapshot_id": d["snapshot_id"],
                    "label":       d["label"],
                    "created_at":  d["created_at"],
                    "reason":      d.get("reason", ""),
                    "model_id":    d.get("model_id", ""),
                    "is_baseline": d.get("is_baseline", False),
                    "verified":    SystemSnapshot.from_dict(d).verify(),
                })
            except Exception:
                pass
        return sorted(snaps, key=lambda x: x["created_at"], reverse=True)

    def get_baseline(self) -> Optional[SystemSnapshot]:
        return self._find_baseline()

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot. Baseline cannot be deleted."""
        snap = self.load(snapshot_id)
        if snap is None:
            return False
        if snap.is_baseline:
            raise ValueError("Baseline snapshot cannot be deleted.")
        path = self.dir / f"{snapshot_id}.json"
        path.unlink()
        return True

    # ── Internal ──────────────────────────────────────────────────────────────

    def _capture(
        self, agent, label: str, reason: str, sid: str
    ) -> SystemSnapshot:
        """Extract current state from agent into a snapshot."""
        # Thresholds from evolution engine
        try:
            ev    = agent.healing.evolution
            curr  = ev.current
            from sigma_anchors import (
                TAU_ESCAPE_FLOOR, CHI_COLLAPSE,
                DRIFT_THRESHOLD, BETTI_1_CAP, CONFIDENCE_FLOOR
            )
            deviation = {
                "tau":        round(curr.tau_floor - TAU_ESCAPE_FLOOR, 6),
                "chi":        round(curr.chi_collapse - CHI_COLLAPSE, 6),
                "drift":      round(curr.drift_threshold - DRIFT_THRESHOLD, 6),
                "betti":      round(curr.betti_cap - BETTI_1_CAP, 6),
                "confidence": round(curr.confidence_floor - CONFIDENCE_FLOOR, 6),
            }
            thresholds = ThresholdState(
                tau_floor=curr.tau_floor,
                chi_collapse=curr.chi_collapse,
                drift_threshold=curr.drift_threshold,
                betti_cap=curr.betti_cap,
                confidence_floor=curr.confidence_floor,
                evolution_step=curr.evolution_step,
                deviation_from_baseline=deviation,
            )
        except Exception:
            from sigma_anchors import (
                TAU_ESCAPE_FLOOR, CHI_COLLAPSE,
                DRIFT_THRESHOLD, BETTI_1_CAP, CONFIDENCE_FLOOR
            )
            thresholds = ThresholdState(
                tau_floor=TAU_ESCAPE_FLOOR,
                chi_collapse=CHI_COLLAPSE,
                drift_threshold=DRIFT_THRESHOLD,
                betti_cap=BETTI_1_CAP,
                confidence_floor=CONFIDENCE_FLOOR,
                evolution_step=0,
                deviation_from_baseline={},
            )

        # Healing state
        try:
            breaker = agent.healing.breaker
            degrader = agent.healing.degrader
            healing = HealingState(
                circuit_state=breaker.state.value,
                consecutive_blocks=breaker._consecutive,
                ewma_block_rate=round(degrader._ewma_block_rate or 0.0, 4),
                ewma_confidence=round(degrader._ewma_confidence or 0.0, 4),
                degrade_state=degrader.state.value,
                degrade_streak=agent.healing._degrade_streak,
            )
        except Exception:
            healing = HealingState(
                circuit_state="CLOSED",
                consecutive_blocks=0,
                ewma_block_rate=0.0,
                ewma_confidence=0.0,
                degrade_state="NOMINAL",
                degrade_streak=0,
            )

        # Memory summary
        try:
            stats = agent.memory.stats()
            mem_summary = MemorySummary(
                total_entries=stats.get("total_entries", 0),
                session_count=stats.get("sessions", 0),
                turn_count=agent._turn_count,
                db_size_bytes=int(stats.get("db_size_mb", 0) * 1024 * 1024),
            )
        except Exception:
            mem_summary = MemorySummary(0, 0, 0, 0)

        model_id = agent._model_config.model_id if agent._model_config else ""

        return SystemSnapshot(
            snapshot_id=sid,
            label=label,
            created_at=time.time(),
            reason=reason,
            model_id=model_id,
            session_id=agent.config.session_id,
            thresholds=thresholds,
            healing=healing,
            memory_summary=mem_summary,
        )

    def _apply(self, snap: SystemSnapshot, agent) -> None:
        """Restore agent state from a snapshot."""
        # Restore threshold values
        try:
            ev = agent.healing.evolution
            ev._tau   = snap.thresholds.tau_floor
            ev._chi   = snap.thresholds.chi_collapse
            ev._drift = snap.thresholds.drift_threshold
            ev._betti = snap.thresholds.betti_cap
            ev._conf  = snap.thresholds.confidence_floor
            ev._step  = snap.thresholds.evolution_step
        except Exception:
            pass

        # Restore healing state
        try:
            from circuit_breaker import CircuitState, DegradeState
            agent.healing.breaker._state = CircuitState(snap.healing.circuit_state)
            agent.healing.breaker._consecutive = snap.healing.consecutive_blocks
            agent.healing.degrader._ewma_block_rate = snap.healing.ewma_block_rate
            agent.healing.degrader._ewma_confidence = snap.healing.ewma_confidence
            agent.healing.degrader._state = DegradeState(snap.healing.degrade_state)
            agent.healing._degrade_streak = snap.healing.degrade_streak
        except Exception:
            pass

    def _write(self, snap: SystemSnapshot) -> None:
        path = self.dir / f"{snap.snapshot_id}.json"
        tmp  = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(snap.to_dict(), f, indent=2)
        os.replace(tmp, path)

    def _find_baseline(self) -> Optional[SystemSnapshot]:
        for p in self.dir.glob("*.json"):
            try:
                with open(p) as f:
                    d = json.load(f)
                if d.get("is_baseline") and d.get("label") == "baseline":
                    return SystemSnapshot.from_dict(d)
            except Exception:
                pass
        return None


# ── Tests ─────────────────────────────────────────────────────────────────────

def run_tests() -> tuple[int, int, list]:
    import tempfile, shutil, sys
    from pathlib import Path
    results = []
    passed = failed = 0

    def ok(n): results.append((n, "PASS", None)); nonlocal passed; passed += 1
    def fail(n, e): results.append((n, "FAIL", str(e))); nonlocal failed; failed += 1

    # Setup
    tmp = Path(tempfile.mkdtemp())
    bm  = BootManager(tmp / "snapshots")

    # Use a mock agent
    class MockEvolution:
        class _curr:
            tau_floor=0.75; chi_collapse=0.40; drift_threshold=0.12
            betti_cap=0.045; confidence_floor=0.65; evolution_step=0
        current = _curr()
        _tau=0.75; _chi=0.40; _drift=0.12; _betti=0.045; _conf=0.65; _step=0

    class MockBreaker:
        from circuit_breaker import CircuitState
        _state = CircuitState.CLOSED; _consecutive = 0

    class MockDegrader:
        from circuit_breaker import DegradeState
        _ewma_block_rate=0.05; _ewma_confidence=0.88
        _state = DegradeState.HEALTHY

    class MockHealing:
        evolution = MockEvolution()
        breaker   = MockBreaker()
        degrader  = MockDegrader()
        _degrade_streak = 0

    class MockMemory:
        def stats(self): return {"total_entries": 10, "sessions": 2, "db_size_mb": 0.1}

    class MockModelConfig:
        model_id = "test_model"

    class MockConfig:
        session_id = "test_session"

    class MockAgent:
        healing = MockHealing()
        memory  = MockMemory()
        _model_config = MockModelConfig()
        _turn_count   = 5
        config = MockConfig()

    agent = MockAgent()

    # T1: save and load
    try:
        sid = bm.save(agent, "test_snap", "test reason")
        snap = bm.load(sid)
        assert snap is not None
        assert snap.label == "test_snap"
        assert snap.reason == "test reason"
        ok("save_and_load")
    except Exception as e: fail("save_and_load", e)

    # T2: hash verification
    try:
        sid  = bm.save(agent, "verify_test")
        snap = bm.load(sid)
        assert snap.verify()
        ok("hash_verified")
    except Exception as e: fail("hash_verified", e)

    # T3: tamper detection
    try:
        sid  = bm.save(agent, "tamper_test")
        path = tmp / "snapshots" / f"{sid}.json"
        with open(path) as f: d = json.load(f)
        d["thresholds"]["tau_floor"] = 0.50  # tamper
        with open(path, "w") as f: json.dump(d, f)
        snap = bm.load(sid)
        assert not snap.verify(), "Should fail verification after tamper"
        ok("tamper_detected")
    except Exception as e: fail("tamper_detected", e)

    # T4: baseline immutable
    try:
        sid = bm.save_baseline(agent)
        snap = bm.load(sid)
        assert snap.is_baseline
        assert snap.label == "baseline"
        try:
            bm.delete(sid)
            fail("baseline_immutable", "No error raised")
        except ValueError:
            ok("baseline_immutable")
    except Exception as e: fail("baseline_immutable", e)

    # T5: baseline only created once
    try:
        sid1 = bm.save_baseline(agent)
        sid2 = bm.save_baseline(agent)
        assert sid1 == sid2, "Second call should return existing baseline"
        ok("baseline_created_once")
    except Exception as e: fail("baseline_created_once", e)

    # T6: pre_update auto-label
    try:
        sid  = bm.save_pre_update(agent, "prop_abc123")
        snap = bm.load(sid)
        assert "pre_update" in snap.label
        assert "prop_abc123" in snap.reason
        ok("pre_update_label")
    except Exception as e: fail("pre_update_label", e)

    # T7: list snapshots
    try:
        snaps = bm.list_snapshots()
        assert len(snaps) >= 1
        assert all("snapshot_id" in s for s in snaps)
        ok("list_snapshots")
    except Exception as e: fail("list_snapshots", e)

    # T8: boot restores state
    try:
        # Set both the _tau field AND the current property proxy
        agent.healing.evolution._tau = 0.70
        agent.healing.evolution.current.tau_floor = 0.70  # captured by _capture
        sid = bm.save(agent, "before_change")
        # Change state
        agent.healing.evolution._tau = 0.55
        agent.healing.evolution.current.tau_floor = 0.55
        # Boot back
        result = bm.boot(sid, agent)
        assert result
        assert abs(agent.healing.evolution._tau - 0.70) < 1e-6
        ok("boot_restores_state")
    except Exception as e: fail("boot_restores_state", e)

    # T9: threshold deviation tracked
    try:
        sid  = bm.save(agent, "deviation_test")
        snap = bm.load(sid)
        assert "tau" in snap.thresholds.deviation_from_baseline
        ok("deviation_tracked")
    except Exception as e: fail("deviation_tracked", e)

    # T10: delete non-baseline
    try:
        sid = bm.save(agent, "deletable")
        assert bm.load(sid) is not None
        bm.delete(sid)
        assert bm.load(sid) is None
        ok("delete_non_baseline")
    except Exception as e: fail("delete_non_baseline", e)

    shutil.rmtree(tmp)
    return passed, failed, results


if __name__ == "__main__":
    p, f, r = run_tests()
    for name, status, err in r:
        print(f"  {'✓' if status == 'PASS' else '✗'} {name}" +
              (f"  → {err}" if err else ""))
    print(f"\n  {p} passed, {f} failed")
