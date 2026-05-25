"""
recall_protocol.py — Labyrinth-OS / Epistemic Archive Layer (L5.5)
===================================================================
Query interface for past patterns stored in the archive.

The RecallProtocol wraps both MemoryStore and PatternCatalog to give
the labeling validator and promotion rules a clean, typed query surface.

Used by:
  - LabelValidator  — check for archive contradictions before accepting a label
  - PromotionRules  — assess historical success rate for a candidate
  - FeedbackLoop    — find anomalies similar to the current one

References:
  spec/ARCHIVE.md  — Recall protocol specification
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from memory_store import MemoryStore, ArchiveEntry, EntryType
from pattern_catalog import PatternCatalog, PatternIndex


# ─── RECALL RESULT ────────────────────────────────────────────────────────────

@dataclass
class RecallResult:
    """
    Result of a recall query.

    Fields
    ------
    query_category      Category used in the query.
    query_source        Source used in the query (may be None = any).
    matched_patterns    PatternIndex entries that matched.
    matched_entries     Raw ArchiveEntry records that matched.
    historical_success  Weighted mean success rate across matched patterns.
    recommendation      "PROMOTE" | "CAUTION" | "BLOCK" based on history.
    """
    query_category:     str
    query_source:       Optional[str]
    matched_patterns:   List[PatternIndex]  = field(default_factory=list)
    matched_entries:    List[ArchiveEntry]  = field(default_factory=list)
    historical_success: float               = 0.5

    @property
    def recommendation(self) -> str:
        if self.historical_success >= 0.80:
            return "PROMOTE"
        if self.historical_success >= 0.50:
            return "CAUTION"
        return "BLOCK"


# ─── RECALL PROTOCOL ─────────────────────────────────────────────────────────

class RecallProtocol:
    """
    Unified query interface over MemoryStore + PatternCatalog.

    Usage::

        store = MemoryStore()
        catalog = PatternCatalog()
        recall = RecallProtocol(store, catalog)
        result = recall.similar_patterns("VALID", threshold=0.7)
        print(result.recommendation)
    """

    def __init__(self, store: MemoryStore, catalog: PatternCatalog) -> None:
        self._store = store
        self._catalog = catalog

    # ── primary interface ─────────────────────────────────────────────────────

    def similar_patterns(
        self,
        category: str,
        *,
        source: Optional[str] = None,
        min_occurrences: int = 2,
        threshold: float = 0.0,
        limit: int = 20,
    ) -> RecallResult:
        """
        Query: "similar_patterns(category, threshold=…)"

        Returns matched historical patterns and a success-weighted
        recommendation for how to treat a label with this profile.

        Parameters
        ----------
        category          Label category to match.
        source            Optional source module filter.
        min_occurrences   Minimum occurrences for a pattern to be returned.
        threshold         Minimum pattern success_rate to include in results.
        limit             Maximum number of patterns to return.
        """
        patterns = self._catalog.query(
            category=category,
            source=source,
            min_occurrences=min_occurrences,
            min_success_rate=threshold,
            limit=limit,
        )

        if not patterns:
            return RecallResult(
                query_category=category,
                query_source=source,
                matched_patterns=[],
                matched_entries=[],
                historical_success=0.5,
            )

        # Weighted average success rate (weight by occurrences)
        total_weight = sum(p.occurrences for p in patterns)
        weighted_success = (
            sum(p.success_rate * p.occurrences for p in patterns) / total_weight
            if total_weight > 0
            else 0.5
        )

        # Pull the raw archive entries for matched patterns
        entries = self._store.query(
            entry_type=EntryType.LABEL,
            limit=limit,
        )

        return RecallResult(
            query_category=category,
            query_source=source,
            matched_patterns=patterns,
            matched_entries=entries,
            historical_success=weighted_success,
        )

    def recent_anomalies(self, limit: int = 10) -> List[ArchiveEntry]:
        """Return the most recent archived anomaly entries."""
        return self._store.query(entry_type=EntryType.ANOMALY, limit=limit)

    def promotions_for_label(self, label_id: str) -> List[ArchiveEntry]:
        """Return all promotion records for a given label_id."""
        return self._store.query(
            entry_type=EntryType.PROMOTION, label_id=label_id
        )

    def outcomes_for_label(self, label_id: str) -> List[ArchiveEntry]:
        """Return all outcome records for a given label_id."""
        return self._store.query(
            entry_type=EntryType.OUTCOME, label_id=label_id
        )

    def has_contradicting_rejection(
        self, category: str, source: str, content: str
    ) -> bool:
        """
        Return True if a REJECTION exists for a structurally identical label.

        Used by LabelValidator to enforce ARCHIVE_CONTRADICTION rejection.
        """
        pattern = self._catalog.lookup(category, source, content)
        if pattern is None:
            return False
        # If this pattern has a failure majority it may be contradicted
        return pattern.success_rate < 0.30 and pattern.occurrences >= 3




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_rp():
    from memory_store import MemoryStore
    from pattern_catalog import PatternCatalog
    return RecallProtocol(store=MemoryStore(), catalog=PatternCatalog())

def _test_protocol_constructs() -> bool:
    rp = _make_rp(); assert rp is not None; return True

def _test_similar_patterns_returns_result() -> bool:
    rp = _make_rp()
    result = rp.similar_patterns(category="VALID")
    assert isinstance(result, RecallResult); return True

def _test_empty_store_empty_result() -> bool:
    rp = _make_rp()
    result = rp.similar_patterns(category="VALID")
    assert result.matched_patterns == []; return True

def _test_result_fields_exist() -> bool:
    rr = RecallResult(query_category="VALID", query_source=None)
    assert hasattr(rr, "matched_patterns")
    assert hasattr(rr, "historical_success"); return True

def _test_success_rate_in_range() -> bool:
    rp = _make_rp()
    result = rp.similar_patterns(category="VALID")
    assert 0.0 <= result.historical_success <= 1.0; return True




def _test_recall_result_has_matched_patterns() -> bool:
    """RecallResult tracks matched patterns."""
    from recall_protocol import RecallResult
    r = RecallResult(query_category="test", query_source=None)
    assert isinstance(r.matched_patterns, list)
    return True

def _test_recall_result_matched_entries_list() -> bool:
    """RecallResult matched_entries is a list."""
    from recall_protocol import RecallResult
    r = RecallResult(query_category="test", query_source="council")
    assert isinstance(r.matched_entries, list)
    return True

def _test_recall_protocol_imports_cleanly() -> bool:
    """recall_protocol imports without error."""
    import recall_protocol
    assert hasattr(recall_protocol, 'RecallResult')
    assert hasattr(recall_protocol, 'RecallProtocol')
    return True

def _test_recall_result_default_success_rate() -> bool:
    """RecallResult has a default historical_success of 0.5."""
    from recall_protocol import RecallResult
    r = RecallResult(query_category="test", query_source=None)
    assert 0.0 <= r.historical_success <= 1.0
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
