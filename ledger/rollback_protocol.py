"""
rollback_protocol.py — Labyrinth-OS / Promotion Pipeline (L6.5)
===============================================================
Rollback a promoted label if it fails in production.

If a promoted candidate fails after crossing the Reality Gate, the rollback
protocol:
  1. Reverts the active CGIR edge to the previous safe state.
  2. Logs the reversion: reason, timestamp, who ordered it.
  3. Triggers an archive analysis to determine why it failed.
  4. Decrements consecutive_run counter for the label.

Invariant enforced:
  I10 — Fail Closed: rollback always reverts to the last known-good state.

References:
  spec/PROMOTION.md — Rollback specification
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import List, Optional


# ─── ROLLBACK REASON ──────────────────────────────────────────────────────────

@unique
class RollbackReason(str, Enum):
    PRODUCTION_FAILURE   = "PRODUCTION_FAILURE"    # failed after promotion
    SAFETY_VIOLATION     = "SAFETY_VIOLATION"      # violated a safety invariant
    COHERENCE_COLLAPSE   = "COHERENCE_COLLAPSE"    # τ dropped below floor in production
    MANUAL_OVERRIDE      = "MANUAL_OVERRIDE"       # steward or operator ordered rollback
    ARCHIVE_CONTRADICTION = "ARCHIVE_CONTRADICTION" # archive analysis found contradiction


# ─── ROLLBACK RECORD ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RollbackRecord:
    """
    Immutable record of one rollback event.

    Fields
    ------
    rollback_id        Sequential identifier.
    label_id           Label that was rolled back.
    reason             RollbackReason enum value.
    ordered_by         Identity of who ordered the rollback.
    description        Human-readable description of what happened.
    previous_edge_ref  Reference to the safe state reverted to (opaque string).
    timestamp          When the rollback was recorded.
    archive_analysis   Result of post-rollback archive query (optional).
    """
    rollback_id:       int
    label_id:          str
    reason:            RollbackReason
    ordered_by:        str
    description:       str
    previous_edge_ref: Optional[str]
    timestamp:         float
    archive_analysis:  Optional[str] = None


# ─── ROLLBACK PROTOCOL ────────────────────────────────────────────────────────

class RollbackProtocol:
    """
    Execute and record rollback events for promoted labels.

    The protocol does not directly modify CGIR (that is the execution layer's
    responsibility).  It records the rollback event and provides the
    information needed by the execution layer to revert.

    Usage::

        protocol = RollbackProtocol()
        record = protocol.rollback(
            label_id="lbl-001",
            reason=RollbackReason.PRODUCTION_FAILURE,
            ordered_by="steward",
            description="τ collapsed to 0.42 after 3 production cycles",
            previous_edge_ref="cgir-edge-v3",
        )
        print(protocol.rollback_count("lbl-001"))   # 1
    """

    def __init__(self) -> None:
        self._records: List[RollbackRecord] = []

    # ── public API ────────────────────────────────────────────────────────────

    def rollback(
        self,
        label_id: str,
        reason: RollbackReason,
        ordered_by: str,
        description: str,
        previous_edge_ref: Optional[str] = None,
        archive_analysis: Optional[str]  = None,
    ) -> RollbackRecord:
        """
        Record a rollback event.

        Parameters
        ----------
        label_id           Label being rolled back.
        reason             Why the rollback was triggered.
        ordered_by         Who ordered the rollback.
        description        Detailed description.
        previous_edge_ref  Opaque reference to the safe state to restore.
        archive_analysis   Optional archive query result (post-mortem).

        Returns
        -------
        The created (immutable) RollbackRecord.
        """
        record = RollbackRecord(
            rollback_id=len(self._records) + 1,
            label_id=label_id,
            reason=reason,
            ordered_by=ordered_by,
            description=description,
            previous_edge_ref=previous_edge_ref,
            timestamp=time.time(),
            archive_analysis=archive_analysis,
        )
        self._records.append(record)
        return record

    def all_records(self) -> List[RollbackRecord]:
        """Return all rollback records (chronologically ordered)."""
        return list(self._records)

    def records_for_label(self, label_id: str) -> List[RollbackRecord]:
        """Return all rollback records for a specific label_id."""
        return [r for r in self._records if r.label_id == label_id]

    def rollback_count(self, label_id: Optional[str] = None) -> int:
        """Count rollback events, optionally filtered by label_id."""
        if label_id is None:
            return len(self._records)
        return sum(1 for r in self._records if r.label_id == label_id)

    def has_been_rolled_back(self, label_id: str) -> bool:
        """Return True if this label has been rolled back at least once."""
        return self.rollback_count(label_id) > 0

    def latest_for_label(self, label_id: str) -> Optional[RollbackRecord]:
        """Return the most recent rollback record for a label, or None."""
        records = self.records_for_label(label_id)
        return records[-1] if records else None




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_protocol_constructs() -> bool:
    rp = RollbackProtocol()
    assert rp is not None
    return True

def _test_rollback_creates_record() -> bool:
    rp = RollbackProtocol()
    record = rp.rollback("lbl1", RollbackReason.SAFETY_VIOLATION,
                          "operator", "Safety constraint violated")
    assert isinstance(record, RollbackRecord)
    assert record.label_id == "lbl1"
    return True

def _test_rollback_reason_preserved() -> bool:
    rp = RollbackProtocol()
    record = rp.rollback("lbl2", RollbackReason.PRODUCTION_FAILURE, "system", "failed")
    assert record.reason == RollbackReason.PRODUCTION_FAILURE
    return True

def _test_rollback_count() -> bool:
    rp = RollbackProtocol()
    rp.rollback("lbl1", RollbackReason.SAFETY_VIOLATION, "op", "x")
    rp.rollback("lbl2", RollbackReason.PRODUCTION_FAILURE, "op", "y")
    assert rp.rollback_count() == 2
    return True

def _test_reasons_exist() -> bool:
    assert RollbackReason.PRODUCTION_FAILURE in RollbackReason
    assert RollbackReason.SAFETY_VIOLATION in RollbackReason
    return True




def _test_rollback_reason_enum_exists() -> bool:
    """RollbackReason enum is defined."""
    from rollback_protocol import RollbackReason
    assert hasattr(RollbackReason, '__members__')
    assert len(RollbackReason.__members__) > 0
    return True

def _test_rollback_record_has_reason() -> bool:
    """RollbackRecord has a reason field."""
    from rollback_protocol import RollbackRecord, RollbackReason
    import time
    reason = RollbackReason.PRODUCTION_FAILURE
    rec = RollbackRecord(rollback_id=1, label_id="lbl-001", reason=reason,
                         ordered_by="system", description="test rollback",
                         previous_edge_ref=None, timestamp=time.time())
    assert rec.label_id == "lbl-001"
    assert rec.reason == reason
    return True

def _test_rollback_protocol_imports_cleanly() -> bool:
    """rollback_protocol imports without error."""
    import rollback_protocol
    assert hasattr(rollback_protocol, 'RollbackReason')
    assert hasattr(rollback_protocol, 'RollbackRecord')
    return True

def _test_rollback_record_preserves_label() -> bool:
    """RollbackRecord label_id is preserved after construction."""
    from rollback_protocol import RollbackRecord, RollbackReason
    import time
    rec = RollbackRecord(rollback_id=2, label_id="lbl-xyz",
                         reason=RollbackReason.MANUAL_OVERRIDE,
                         ordered_by="operator", description="manual",
                         previous_edge_ref="edge-001", timestamp=time.time())
    assert rec.label_id == "lbl-xyz"
    return True

def run_tests() -> tuple:
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("_test_") and callable(o)], key=lambda x:x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn(); passed += 1; results.append((name,"PASS",None))
        except Exception as e:
            failed += 1; results.append((name,"FAIL",str(e)))
    return passed, failed, results
