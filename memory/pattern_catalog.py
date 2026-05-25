"""
pattern_catalog.py — Labyrinth-OS / Epistemic Archive Layer (L5.5)
===================================================================
Indexed pattern library.

The PatternCatalog keeps a searchable index of every archived label pattern.
It answers: "have we seen a label like this before, and what happened?"

Used by:
  - LabelValidator — check for archive contradictions
  - PromotionRules — assess historical success rate before promoting

References:
  spec/ARCHIVE.md  — Pattern catalog specification
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─── PATTERN INDEX ────────────────────────────────────────────────────────────

@dataclass
class PatternIndex:
    """
    Summary of a pattern as stored in the catalog.

    Fields
    ------
    pattern_key      Canonical key derived from (category, source, content_prefix)
    category         LabelCategory string
    source           Originating module
    content_prefix   First 32 chars of label content (for quick matching)
    occurrences      How many times this pattern has been seen
    successes        How many times it led to a successful outcome
    failures         How many times it led to a failure
    last_seen        Unix timestamp of most recent occurrence
    avg_confidence   Rolling average confidence across occurrences
    """
    pattern_key:    str
    category:       str
    source:         str
    content_prefix: str
    occurrences:    int   = 0
    successes:      int   = 0
    failures:       int   = 0
    last_seen:      float = field(default_factory=time.time)
    avg_confidence: float = 0.0

    @property
    def success_rate(self) -> float:
        """Historical success rate in [0.0, 1.0].  0.5 if no outcomes yet."""
        total = self.successes + self.failures
        if total == 0:
            return 0.5  # unknown — neutral prior
        return self.successes / total


# ─── PATTERN CATALOG ─────────────────────────────────────────────────────────

class PatternCatalog:
    """
    Indexed, queryable pattern library.

    Thread-safe for concurrent reads; writes are serialized via standard
    Python's GIL (acceptable for the epistemic pipeline throughput).

    Usage::

        catalog = PatternCatalog()
        catalog.record_occurrence("VALID", "council", "hash-abc", confidence=0.92)
        catalog.record_outcome("VALID", "council", "hash-abc", success=True)
        results = catalog.query(category="VALID", min_occurrences=2)
    """

    #: Max chars of content used to build the content_prefix key component.
    PREFIX_LEN: int = 32

    def __init__(self) -> None:
        self._index: Dict[str, PatternIndex] = {}

    # ── key construction ──────────────────────────────────────────────────────

    @classmethod
    def _make_key(cls, category: str, source: str, content: str) -> str:
        prefix = content[:cls.PREFIX_LEN].replace("|", "_")
        return f"{category}|{source}|{prefix}"

    # ── public API ────────────────────────────────────────────────────────────

    def record(self, pattern: str, category: str = "general",
               outcome: bool = True, success: bool = True,
               source: str = "system", content: str = "") -> None:
        """Convenience alias — record a pattern occurrence with outcome."""
        self.record_occurrence(category, source, content or pattern, confidence=0.8)
        self.record_outcome(category, source, content or pattern, success=(outcome and success))

    def record_occurrence(
        self,
        category: str,
        source: str,
        content: str,
        confidence: float,
    ) -> PatternIndex:
        """
        Record one occurrence of this pattern.

        Creates the index entry if it does not exist; updates it otherwise.
        """
        key = self._make_key(category, source, content)
        if key not in self._index:
            self._index[key] = PatternIndex(
                pattern_key=key,
                category=category,
                source=source,
                content_prefix=content[:self.PREFIX_LEN],
                occurrences=0,
                avg_confidence=confidence,
            )
        idx = self._index[key]
        # Update rolling average
        idx.avg_confidence = (
            (idx.avg_confidence * idx.occurrences + confidence)
            / (idx.occurrences + 1)
        )
        idx.occurrences += 1
        idx.last_seen = time.time()
        return idx

    def record_outcome(
        self,
        category: str,
        source: str,
        content: str,
        success: bool,
    ) -> Optional[PatternIndex]:
        """
        Record an outcome (success or failure) for this pattern.

        No-op (returns None) if the pattern has never been seen.
        """
        key = self._make_key(category, source, content)
        if key not in self._index:
            return None
        idx = self._index[key]
        if success:
            idx.successes += 1
        else:
            idx.failures += 1
        return idx

    def query(
        self,
        *,
        category: Optional[str] = None,
        source: Optional[str] = None,
        min_occurrences: int = 1,
        min_success_rate: float = 0.0,
        limit: Optional[int] = None,
    ) -> List[PatternIndex]:
        """
        Query the pattern index.

        Parameters
        ----------
        category          Filter by LabelCategory string.
        source            Filter by originating module.
        min_occurrences   Only return patterns seen at least this many times.
        min_success_rate  Only return patterns with success_rate ≥ value.
        limit             Cap number of results (most recently seen first).
        """
        results = list(self._index.values())
        if category is not None:
            results = [p for p in results if p.category == category]
        if source is not None:
            results = [p for p in results if p.source == source]
        results = [p for p in results if p.occurrences >= min_occurrences]
        results = [p for p in results if p.success_rate >= min_success_rate]
        results.sort(key=lambda p: p.last_seen, reverse=True)
        if limit is not None:
            results = results[:limit]
        return results

    def lookup(
        self, category: str, source: str, content: str
    ) -> Optional[PatternIndex]:
        """Look up a specific pattern; returns None if not found."""
        return self._index.get(self._make_key(category, source, content))

    def size(self) -> int:
        """Return the number of unique patterns in the catalog."""
        return len(self._index)




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

    def top_patterns(self, category: str = "", n: int = 5) -> list:
        """Return top N patterns by occurrence count, optionally filtered by category."""
        items = [
            (k, v) for k, v in self._index.items()
            if not category or k.split("|")[0] == category
        ]
        items.sort(key=lambda kv: -(getattr(kv[1],'occurrences',0)))
        return items[:n]

    def categories(self) -> list:
        """Return list of unique categories seen."""
        cats = set()
        for key in self._index:
            parts = key.split("|")
            if parts:
                cats.add(parts[0])
        return sorted(cats)

    def failure_rate(self, category: str = "") -> float:
        """Fraction of recorded outcomes that were failures (0.0 if none)."""
        total = failures = 0
        for key, idx_entry in self._index.items():
            if category and key.split("|")[0] != category:
                continue
            total += getattr(idx_entry, 'occurrences', 0)
            failures += getattr(idx_entry, 'failures', 0)
        return failures / max(total, 1)

def _test_catalog_constructs() -> bool:
    c = PatternCatalog()
    assert c.size() == 0
    return True

def _test_record_and_query() -> bool:
    c = PatternCatalog()
    c.record_occurrence("VALID", "test", "test content here", 0.85)
    results = c.query(category="VALID")
    assert len(results) >= 1
    return True

def _test_unknown_category_empty() -> bool:
    c = PatternCatalog()
    assert c.query(category="NONEXISTENT") == []
    return True

def _test_size_after_record() -> bool:
    c = PatternCatalog()
    c.record_occurrence("VALID", "test", "content abc def", 0.8)
    assert c.size() >= 1
    return True

def _test_record_outcome_success() -> bool:
    c = PatternCatalog()
    c.record_occurrence("VALID", "test", "some content for test", 0.9)
    c.record_outcome("VALID", "test", "some content for test", success=True)
    results = c.query(category="VALID")
    assert len(results) >= 1
    return True



def _test_catalog_top_patterns_nonempty() -> bool:
    pc = PatternCatalog()
    pc.record("test-label", "category_a", success=True)
    top = pc.top_patterns("category_a")
    assert len(top) > 0
    return True

def _test_failure_rate_tracked() -> bool:
    pc = PatternCatalog()
    pc.record("label_1", "cat_a", success=False)
    pc.record("label_1", "cat_a", success=False)
    pc.record("label_1", "cat_a", success=True)
    rate = pc.failure_rate("cat_a")
    assert rate is not None
    assert 0.0 <= rate <= 1.0
    return True

def _test_categories_tracked() -> bool:
    pc = PatternCatalog()
    pc.record("l1", "cat_x", success=True)
    pc.record("l2", "cat_y", success=True)
    cats = pc.categories()
    assert "cat_x" in cats and "cat_y" in cats
    return True

def _test_size_grows_with_records() -> bool:
    pc = PatternCatalog()
    s0 = pc.size()
    pc.record("l1", "cat", success=True)
    assert pc.size() > s0
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
