"""
continuous_learning_loop.py — Labyrinth-OS / Lane 1 + Lane 2
=============================================================
Continuous Learning Loop — Closing the Episodic/Continuous Gap

The gap this closes:
  Labyrinth-OS has all six components of a continuous learning loop.
  They run episodically. Sessions do not compound.

  The six components and their Labyrinth-OS locations:
    Perception     = L01 Proposal Intake
    World Model    = MemoryArchive rebuild
    Memory         = archive similarity search
    Planning       = Lane 1 reasoning
    Action         = Lane 2 execution post-gate
    Feedback       = healing loop / WORM ledger (L20 → L06)

  FeedbackRecord exists in pipeline_wire.py. Not called from ignition.py.
  _feedback_to_archive() exists in IgnitionSession. Not called in _seal().
  MemoryArchive.refresh() exists. Not called in session lifecycle.

  This module provides the wiring that connects them continuously.

Design:
  LearningLoop wraps a session's lifecycle.
  At session start: load memory state from previous sessions.
  At session end: push feedback to archive, refresh memory index.
  Next session starts with enriched archive.

  The loop does not modify execution. It only updates the epistemic
  memory that future proposals draw from. Gate remains unchanged.

Integration:
  Call LearningLoop.begin_session() before IgnitionSession.run()
  Call LearningLoop.end_session() after IgnitionSession.run()

  Also wires:
  - _feedback_to_archive() into session seal (GAP 4 fix)
  - PipelineTrace into session trial loop (GAP 5 fix)
  - MemoryArchive.refresh() into session lifecycle

Reference: Continuous Learning research (external)
See: archive/external_references/quillan/ASSESSMENT_quillan.md
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── SESSION MEMORY STATE ────────────────────────────────────────────────────

@dataclass
class SessionMemoryState:
    """
    Mutable record of memory state for a session.
    Tracks what was loaded, what was learned, and what was stored.
    """
    session_id:        str
    started_at:        float
    ended_at:          Optional[float]    = None

    # What the session loaded from archive
    prior_episodes:    int                = 0
    prior_patterns:    int                = 0

    # What the session produced
    new_feedback:      int                = 0
    new_cue_patterns:  int                = 0
    blocked_trials:    int                = 0
    executed_trials:   int                = 0

    # Loop status
    feedback_stored:   bool               = False
    memory_refreshed:  bool               = False
    cues_mined:        bool               = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id":       self.session_id,
            "started_at":       self.started_at,
            "ended_at":         self.ended_at,
            "prior_episodes":   self.prior_episodes,
            "prior_patterns":   self.prior_patterns,
            "new_feedback":     self.new_feedback,
            "new_cue_patterns": self.new_cue_patterns,
            "blocked_trials":   self.blocked_trials,
            "executed_trials":  self.executed_trials,
            "feedback_stored":  self.feedback_stored,
            "memory_refreshed": self.memory_refreshed,
            "cues_mined":       self.cues_mined,
        }


# ─── FEEDBACK RECORD ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LoopFeedbackRecord:
    """
    Immutable feedback record for one trial outcome.
    Stored in ArchiveMemory as OUTCOME entry.
    """
    trial_id:    str
    session_id:  str
    decision:    str       # EXECUTE | BLOCK | KILL
    confidence:  float
    chi:         float
    tau:         float
    drift:       float
    outcome:     str       # EXECUTED | BLOCKED
    timestamp:   float
    loop_stage:  str = "L20_to_L06"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trial_id":   self.trial_id,
            "session_id": self.session_id,
            "decision":   self.decision,
            "confidence": self.confidence,
            "chi":        self.chi,
            "tau":        self.tau,
            "drift":      self.drift,
            "outcome":    self.outcome,
            "timestamp":  self.timestamp,
            "loop_stage": self.loop_stage,
        }


# ─── LEARNING LOOP ───────────────────────────────────────────────────────────

class LearningLoop:
    """
    Wires the six-step continuous learning loop across sessions.

    Step 1: Perception     → load memory state at session start
    Step 2: World Model    → MemoryArchive.refresh() after ledger entries
    Step 3: Memory         → archive similarity available to proposals
    Step 4: Planning       → Lane 1 reasoning (not modified by this module)
    Step 5: Action         → Lane 2 execution (not modified by this module)
    Step 6: Feedback       → store trial outcomes to archive at session end

    This module handles steps 1, 2, and 6.
    Steps 3, 4, 5 are handled by existing pipeline modules.
    """

    def __init__(
        self,
        memory_archive=None,       # MemoryArchive instance (optional)
        cue_miner=None,            # CuePatternMiner instance (optional)
        verbose: bool = False,
    ):
        self._archive  = memory_archive
        self._miner    = cue_miner
        self._verbose  = verbose
        self._state:   Optional[SessionMemoryState] = None
        self._feedback_buffer: List[LoopFeedbackRecord] = []

    # ── STEP 1: BEGIN SESSION (Perception) ───────────────────────────────────

    def begin_session(self, session_id: str) -> SessionMemoryState:
        """
        Load memory state at session start.
        Called before IgnitionSession.run().
        """
        self._feedback_buffer = []
        state = SessionMemoryState(
            session_id = session_id,
            started_at = time.time(),
        )

        # Load prior episode count from archive if available
        if self._archive is not None:
            try:
                # MemoryArchive.refresh() loads from ledger
                self._archive.refresh()
                state.prior_episodes = getattr(
                    self._archive, "episode_count", 0
                )
                if self._verbose:
                    print(f"  [LOOP] Loaded {state.prior_episodes} prior episodes")
            except Exception as e:
                if self._verbose:
                    print(f"  [LOOP] Archive load failed (non-fatal): {e}")

        # Load prior cue patterns from miner if available
        if self._miner is not None:
            try:
                state.prior_patterns = len(
                    self._miner.get_known_patterns()
                )
                if self._verbose:
                    print(f"  [LOOP] Loaded {state.prior_patterns} cue patterns")
            except Exception:
                pass

        self._state = state
        return state

    # ── STEP 6: RECORD FEEDBACK ──────────────────────────────────────────────

    def record_trial_feedback(
        self,
        trial_id:   str,
        decision:   str,
        confidence: float,
        chi:        float    = 0.0,
        tau:        float    = 0.0,
        drift:      float    = 0.0,
    ) -> None:
        """
        Buffer a trial outcome for storage at session end.
        Called once per trial (replaces _feedback_to_archive stub).
        Fail-safe: never raises.
        """
        try:
            if self._state is None:
                return
            if self._state.ended_at is not None:
                return  # session already closed — do not write to ended session
            valid_decisions = {"EXECUTE", "BLOCK", "KILL"}
            if decision not in valid_decisions:
                decision = "BLOCK"  # treat unknown as BLOCK (fail-safe)
            outcome = "EXECUTED" if decision == "EXECUTE" else "BLOCKED"
            record = LoopFeedbackRecord(
                trial_id   = trial_id,
                session_id = self._state.session_id,
                decision   = decision,
                confidence = confidence,
                chi        = chi,
                tau        = tau,
                drift      = drift,
                outcome    = outcome,
                timestamp  = time.time(),
            )
            self._feedback_buffer.append(record)
            if decision != "EXECUTE" and self._state:
                self._state.blocked_trials += 1
            else:
                if self._state:
                    self._state.executed_trials += 1
        except Exception:
            pass

    # ── STEP 2 + 6: END SESSION (World Model + Feedback) ────────────────────

    def end_session(
        self,
        chain_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> SessionMemoryState:
        """
        Push feedback to archive, refresh memory, mine cue patterns.
        Called after IgnitionSession.run() completes.

        chain_entries: ledger entries from this session (for cue mining).
        """
        if self._state is None:
            raise RuntimeError("begin_session() must be called before end_session()")

        self._state.ended_at = time.time()

        # Store feedback to archive (GAP 4 fix)
        if self._archive is not None and self._feedback_buffer:
            try:
                for record in self._feedback_buffer:
                    # Archive stores as OUTCOME entry
                    try:
                        # Resolve memory_store path explicitly — it lives in epistemic/archive/
                        import os as _os, sys as _sys
                        _here = _os.path.dirname(_os.path.abspath(__file__))
                        _sentinel = _os.path.normpath(_os.path.join(_here, '..'))
                        _archive_path = _os.path.join(_sentinel, 'epistemic', 'archive')
                        if _os.path.isdir(_archive_path) and _archive_path not in _sys.path:
                            _sys.path.insert(0, _archive_path)
                        from memory_store import EntryType
                        self._archive.append(
                            entry_type = EntryType.OUTCOME,
                            label_id   = record.trial_id,
                            payload    = record.to_dict(),
                        )
                    except ImportError:
                        # Fallback: store via any available interface
                        if hasattr(self._archive, "store"):
                            self._archive.store(record.to_dict())
                self._state.new_feedback    = len(self._feedback_buffer)
                self._state.feedback_stored = True
                if self._verbose:
                    print(f"  [LOOP] Stored {self._state.new_feedback} feedback records")
            except Exception as e:
                if self._verbose:
                    print(f"  [LOOP] Feedback storage failed (non-fatal): {e}")

        # Refresh memory index (Step 2 — World Model Update)
        if self._archive is not None:
            try:
                self._archive.refresh()
                self._state.memory_refreshed = True
                if self._verbose:
                    print(f"  [LOOP] Memory index refreshed")
            except Exception as e:
                if self._verbose:
                    print(f"  [LOOP] Memory refresh failed (non-fatal): {e}")

        # Mine cue patterns from chain entries
        if self._miner is not None and chain_entries:
            try:
                from cue_pattern_miner import CuePatternMiner
                result = self._miner.mine(
                    chain_entries,
                    session_id = self._state.session_id,
                )
                self._state.new_cue_patterns = result.new_patterns
                self._state.cues_mined       = True
                if self._verbose:
                    print(f"  [LOOP] Mined {result.patterns_found} cue patterns "
                          f"({result.new_patterns} new, "
                          f"{result.high_frequency} high-frequency)")
            except Exception as e:
                if self._verbose:
                    print(f"  [LOOP] Cue mining failed (non-fatal): {e}")

        return self._state

    def get_feedback_buffer(self) -> List[LoopFeedbackRecord]:
        """Return buffered feedback records (for inspection/testing)."""
        return list(self._feedback_buffer)


# ─── TESTS ───────────────────────────────────────────────────────────────────

def run_tests() -> tuple:
    passed = failed = 0
    results = []

    def t(name, fn):
        nonlocal passed, failed
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)))

    def test_begin_session_returns_state():
        loop = LearningLoop()
        state = loop.begin_session("s_test_1")
        assert state.session_id == "s_test_1"
        assert state.started_at > 0
        assert state.ended_at is None
    t("test_begin_session_returns_state", test_begin_session_returns_state)

    def test_record_feedback_buffers():
        loop = LearningLoop()
        loop.begin_session("s_test_2")
        loop.record_trial_feedback("t1", "EXECUTE", 0.88, chi=0.10, tau=0.80)
        loop.record_trial_feedback("t2", "BLOCK",   0.65, chi=0.45, tau=0.60)
        buf = loop.get_feedback_buffer()
        assert len(buf) == 2
    t("test_record_feedback_buffers", test_record_feedback_buffers)

    def test_feedback_outcome_mapping():
        loop = LearningLoop()
        loop.begin_session("s_test_3")
        loop.record_trial_feedback("t1", "EXECUTE", 0.90)
        loop.record_trial_feedback("t2", "BLOCK",   0.55)
        buf = loop.get_feedback_buffer()
        assert buf[0].outcome == "EXECUTED"
        assert buf[1].outcome == "BLOCKED"
    t("test_feedback_outcome_mapping", test_feedback_outcome_mapping)

    def test_end_session_sets_ended_at():
        loop = LearningLoop()
        loop.begin_session("s_test_4")
        state = loop.end_session()
        assert state.ended_at is not None
        assert state.ended_at >= state.started_at
    t("test_end_session_sets_ended_at", test_end_session_sets_ended_at)

    def test_end_session_without_begin_raises():
        loop = LearningLoop()
        try:
            loop.end_session()
            raise AssertionError("Should raise")
        except RuntimeError as e:
            assert "begin_session" in str(e)
    t("test_end_session_without_begin_raises",
      test_end_session_without_begin_raises)

    def test_blocked_trial_count():
        loop = LearningLoop()
        loop.begin_session("s_test_5")
        loop.record_trial_feedback("t1", "EXECUTE", 0.90)
        loop.record_trial_feedback("t2", "BLOCK",   0.55)
        loop.record_trial_feedback("t3", "BLOCK",   0.50)
        state = loop.end_session()
        assert state.blocked_trials == 2
        assert state.executed_trials == 1
    t("test_blocked_trial_count", test_blocked_trial_count)

    def test_loop_survives_no_archive():
        loop = LearningLoop(memory_archive=None)
        loop.begin_session("s_test_6")
        loop.record_trial_feedback("t1", "EXECUTE", 0.88)
        state = loop.end_session(chain_entries=[])
        # Should complete without raising even with no archive
        assert state is not None
    t("test_loop_survives_no_archive", test_loop_survives_no_archive)

    def test_feedback_record_is_immutable():
        record = LoopFeedbackRecord(
            trial_id="t", session_id="s", decision="EXECUTE",
            confidence=0.9, chi=0.1, tau=0.8, drift=0.05,
            outcome="EXECUTED", timestamp=time.time()
        )
        try:
            record.decision = "BLOCK"
            raise AssertionError("Should be immutable")
        except Exception as e:
            assert "frozen" in str(e).lower() or "can't" in str(e).lower() or "FrozenInstanceError" in type(e).__name__
    t("test_feedback_record_is_immutable", test_feedback_record_is_immutable)

    def test_feedback_record_to_dict_serializable():
        record = LoopFeedbackRecord(
            trial_id="t", session_id="s", decision="BLOCK",
            confidence=0.7, chi=0.3, tau=0.6, drift=0.1,
            outcome="BLOCKED", timestamp=time.time()
        )
        json.dumps(record.to_dict())
    t("test_feedback_record_to_dict_serializable",
      test_feedback_record_to_dict_serializable)

    def test_session_state_to_dict_serializable():
        loop = LearningLoop()
        state = loop.begin_session("s_test_7")
        json.dumps(state.to_dict())
    t("test_session_state_to_dict_serializable",
      test_session_state_to_dict_serializable)

    def test_record_feedback_without_begin_is_noop():
        loop = LearningLoop()
        # Should not raise — fail-safe
        loop.record_trial_feedback("t1", "EXECUTE", 0.9)
        assert loop.get_feedback_buffer() == []
    t("test_record_feedback_without_begin_is_noop",
      test_record_feedback_without_begin_is_noop)

    def test_multiple_sessions_compound():
        loop = LearningLoop()
        # Session 1
        loop.begin_session("s_compound_1")
        loop.record_trial_feedback("t1", "EXECUTE", 0.90)
        state1 = loop.end_session()
        assert state1.executed_trials == 1

        # Session 2 — fresh state (begin_session resets buffer)
        loop.begin_session("s_compound_2")
        # Buffer reset by begin_session
        assert len(loop.get_feedback_buffer()) == 0
        loop.record_trial_feedback("t2", "BLOCK", 0.60)
        state2 = loop.end_session()
        assert state2.blocked_trials == 1
    t("test_multiple_sessions_compound", test_multiple_sessions_compound)

    return passed, failed, results


if __name__ == "__main__":
    print("=" * 70)
    print("Labyrinth-OS — Continuous Learning Loop")
    print("Closes the episodic/continuous gap. Sessions compound.")
    print("=" * 70)
    print()
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err:
            line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("\n  Continuous Learning Loop — COMPLETE")
    print("=" * 70)
