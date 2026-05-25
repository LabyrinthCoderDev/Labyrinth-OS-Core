"""
anomaly_log.py — Labyrinth-OS / Observability Layer (L5.75)
============================================================
Append-only log of system anomalies detected during the epistemic pipeline.

Every anomaly is linked to: timestamp, metric, label, confidence, and
the drift alert (if any) that triggered it.  Anomaly records feed the
FeedbackLoop which closes the observability → labeling cycle.

References:
  spec/OBSERVABILITY.md
  INVARIANTS.md — I13 Observability completeness
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import List, Optional


# ─── ANOMALY SEVERITY ─────────────────────────────────────────────────────────

@unique
class AnomalySeverity(str, Enum):
    WARN     = "WARN"
    ERROR    = "ERROR"
    CRITICAL = "CRITICAL"


# ─── ANOMALY ENTRY ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AnomalyEntry:
    """
    One immutable anomaly record.

    Fields
    ------
    anomaly_id   Sequential id within this log instance.
    severity     AnomalySeverity.
    metric       Metric that triggered the anomaly (e.g., "tau", "drift").
    description  Human-readable description.
    timestamp    Unix epoch float.
    label_id     Associated label (may be None).
    confidence   Confidence value at time of anomaly (may be None).
    """
    anomaly_id:  int
    severity:    AnomalySeverity
    metric:      str
    description: str
    timestamp:   float
    label_id:    Optional[str]
    confidence:  Optional[float]


# ─── ANOMALY LOG ─────────────────────────────────────────────────────────────

class AnomalyLog:
    """
    Append-only log of detected anomalies.

    No deletion, no modification.  Analogous to MemoryStore but lightweight
    (no hash chain needed — anomalies are linked to MemoryStore via the
    FeedbackLoop).

    Usage::

        log = AnomalyLog()
        entry = log.append(
            severity=AnomalySeverity.ERROR,
            metric="drift",
            description="τ drifted by 0.18 from baseline",
            label_id="lbl-001",
            confidence=0.72,
        )
        print(log.count())       # 1
        print(log.has_critical)  # False
    """

    def __init__(self) -> None:
        self._entries: List[AnomalyEntry] = []

    # ── public API ────────────────────────────────────────────────────────────

    def append(
        self,
        severity: AnomalySeverity,
        metric: str,
        description: str,
        label_id: Optional[str] = None,
        confidence: Optional[float] = None,
        timestamp: Optional[float] = None,
    ) -> AnomalyEntry:
        """
        Append a new anomaly entry.

        Returns the created (immutable) AnomalyEntry.
        """
        entry = AnomalyEntry(
            anomaly_id=len(self._entries) + 1,
            severity=severity,
            metric=metric,
            description=description,
            timestamp=timestamp or time.time(),
            label_id=label_id,
            confidence=confidence,
        )
        self._entries.append(entry)
        return entry

    def query(
        self,
        *,
        severity: Optional[AnomalySeverity] = None,
        metric: Optional[str] = None,
        label_id: Optional[str] = None,
        since: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> List[AnomalyEntry]:
        """
        Query anomaly entries with optional filters.

        Results are chronologically ordered (oldest first).
        """
        results = list(self._entries)
        if severity is not None:
            results = [e for e in results if e.severity == severity]
        if metric is not None:
            results = [e for e in results if e.metric == metric]
        if label_id is not None:
            results = [e for e in results if e.label_id == label_id]
        if since is not None:
            results = [e for e in results if e.timestamp >= since]
        if limit is not None:
            results = results[-limit:]
        return results

    @property
    def has_critical(self) -> bool:
        """Return True if any CRITICAL anomaly is in the log."""
        return any(e.severity == AnomalySeverity.CRITICAL for e in self._entries)

    def count(self, severity: Optional[AnomalySeverity] = None) -> int:
        """Return total entries, optionally filtered by severity."""
        if severity is None:
            return len(self._entries)
        return sum(1 for e in self._entries if e.severity == severity)

    def latest(self) -> Optional[AnomalyEntry]:
        """Return the most recently appended entry."""
        return self._entries[-1] if self._entries else None



def _test_log_constructs() -> bool:
    log = AnomalyLog()
    assert log.count() == 0
    return True

def _test_append_and_count() -> bool:
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.WARN, metric="chi", description="chi elevated")
    assert log.count() == 1
    return True

def _test_has_critical_false_when_only_warn() -> bool:
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.WARN, metric="chi", description="minor")
    assert not log.has_critical
    return True

def _test_has_critical_true_when_critical() -> bool:
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.CRITICAL, metric="tau",
               description="tau collapse", label_id="L001")
    assert log.has_critical
    return True

def _test_query_by_severity() -> bool:
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.WARN, metric="chi", description="w")
    log.append(severity=AnomalySeverity.CRITICAL, metric="tau", description="c")
    warns = log.query(severity=AnomalySeverity.WARN)
    assert len(warns) == 1
    return True

def _test_query_by_label() -> bool:
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.WARN, metric="chi",
               description="x", label_id="L001")
    log.append(severity=AnomalySeverity.WARN, metric="chi",
               description="y", label_id="L002")
    results = log.query(label_id="L001")
    assert len(results) == 1
    return True

def _test_latest_returns_most_recent() -> bool:
    log = AnomalyLog()
    log.append(severity=AnomalySeverity.WARN, metric="chi", description="first")
    log.append(severity=AnomalySeverity.ERROR, metric="drift", description="second")
    latest = log.latest()
    assert latest is not None
    assert latest.description == "second"
    return True

def _test_no_delete_method() -> bool:
    log = AnomalyLog()
    assert not hasattr(log, "delete")
    assert not hasattr(log, "remove")
    assert not hasattr(log, "clear")
    return True


def run_tests() -> tuple:
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("_test_") and callable(o)], key=lambda x: x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn(); passed += 1; results.append((name, "PASS", None))
        except Exception as e:
            failed += 1; results.append((name, "FAIL", str(e)))
    return passed, failed, results
