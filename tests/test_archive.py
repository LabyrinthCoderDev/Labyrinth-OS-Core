"""
tests/epistemic/test_archive.py — Labyrinth-OS
================================================
Epistemic pipeline tests: archive memory layer.

Run with:
    python -m pytest tests/epistemic/test_archive.py -v
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/archive"))

from memory_store import MemoryStore, EntryType
from pattern_catalog import PatternCatalog
from confidence_record import ConfidenceRecord, LabelOutcome
from recall_protocol import RecallProtocol


class TestArchivePipeline(unittest.TestCase):

    def test_append_only_chain_integrity(self):
        """Appending 100 entries leaves a valid chain."""
        store = MemoryStore()
        for i in range(100):
            store.append(EntryType.LABEL, f"lbl-{i}", {"idx": i})
        self.assertTrue(store.verify())

    def test_chain_tip_changes_with_each_append(self):
        store = MemoryStore()
        tips = set()
        for i in range(5):
            store.append(EntryType.LABEL, f"lbl-{i}", {})
            tips.add(store.tip_hash())
        self.assertEqual(len(tips), 5)

    def test_pattern_catalog_tracks_success_rate(self):
        catalog = PatternCatalog()
        for _ in range(4):
            catalog.record_occurrence("VALID", "council", "hash-x", 0.90)
            catalog.record_outcome("VALID", "council", "hash-x", success=True)
        catalog.record_occurrence("VALID", "council", "hash-x", 0.90)
        catalog.record_outcome("VALID", "council", "hash-x", success=False)
        idx = catalog.lookup("VALID", "council", "hash-x")
        self.assertAlmostEqual(idx.success_rate, 4 / 5)

    def test_confidence_record_accuracy(self):
        record = ConfidenceRecord()
        # 9 correct, 1 wrong
        for i in range(9):
            record.record_prediction(f"lbl-{i}", 0.92)
            record.record_outcome(f"lbl-{i}", LabelOutcome.SUCCESS)
        record.record_prediction("lbl-wrong", 0.92)
        record.record_outcome("lbl-wrong", LabelOutcome.FAILURE)
        acc = record.accuracy()
        self.assertAlmostEqual(acc, 0.9)

    def test_recall_protocol_recommendation_logic(self):
        store = MemoryStore()
        catalog = PatternCatalog()
        recall = RecallProtocol(store, catalog)

        # High-success pattern
        for _ in range(5):
            catalog.record_occurrence("VALID", "council", "good-hash", 0.92)
            catalog.record_outcome("VALID", "council", "good-hash", success=True)

        result = recall.similar_patterns("VALID", min_occurrences=2)
        self.assertEqual(result.recommendation, "PROMOTE")

    def test_archive_has_no_delete_method(self):
        store = MemoryStore()
        self.assertFalse(hasattr(store, "delete"))
        self.assertFalse(hasattr(store, "modify"))

    def test_recall_detects_archive_contradiction(self):
        store = MemoryStore()
        catalog = PatternCatalog()
        recall = RecallProtocol(store, catalog)
        # Repeatedly failing pattern
        for _ in range(3):
            catalog.record_occurrence("VALID", "council", "bad-content", 0.90)
            catalog.record_outcome("VALID", "council", "bad-content", success=False)
        self.assertTrue(
            recall.has_contradicting_rejection("VALID", "council", "bad-content")
        )




def run_tests() -> tuple:
    """Labyrinth-OS standard runner — wraps unittest for run_all.py compatibility."""
    import unittest, io, sys, os
    # Add all relevant paths
    _BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    for _sub in [
        os.path.join(_BASE, 'epistemic', 'labeling'),
        os.path.join(_BASE, 'epistemic', 'archive'),
        os.path.join(_BASE, 'promotion'),
        os.path.join(_BASE, 'execution', 'observability'),
        os.path.join(_BASE, 'execution', 'pre_cgir_gate'),
    ]:
        if os.path.isdir(_sub) and _sub not in sys.path:
            sys.path.insert(0, _sub)

    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    buf    = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    results = []
    for test, tb in result.failures + result.errors:
        results.append((str(test), "FAIL", tb.strip().split("\n")[-1]))
    for i in range(passed):
        results.append((f"test_{i:03}", "PASS", None))
    return passed, failed, results


if __name__ == "__main__":
    import unittest
    unittest.main()
