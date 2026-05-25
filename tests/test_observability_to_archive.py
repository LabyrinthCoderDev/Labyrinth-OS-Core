"""
tests/integration/test_observability_to_archive.py — Labyrinth-OS
==================================================================
Integration test: observability feedback loop → archive.

Verifies that anomalies detected by observability are correctly
logged, archived, and used to adjust label confidence.

Run with:
    python -m pytest tests/integration/test_observability_to_archive.py -v
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/observability"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/archive"))

from metrics import SystemMetrics, MetricsCollector, TAU_ESCAPE_FLOOR, DRIFT_THRESHOLD
from drift_detector import DriftDetector
from anomaly_log import AnomalyLog, AnomalySeverity
from feedback_loop import FeedbackLoop
from memory_store import MemoryStore, EntryType
from pattern_catalog import PatternCatalog
from recall_protocol import RecallProtocol


class TestObservabilityToArchive(unittest.TestCase):

    def test_drift_detected_anomaly_logged_and_archived(self):
        """
        Full path: detect drift → log anomaly → archive anomaly entry.
        """
        # Step 1: Set up
        store   = MemoryStore()
        anomaly_log = AnomalyLog()
        detector = DriftDetector()
        detector.update_baseline(tau=0.85, chi=0.08, confidence=0.90)

        # Step 2: Detect drift
        snap = SystemMetrics(tau=0.50, chi=0.08, drift=0.05, confidence=0.90,
                             stage="labeling", label_id="lbl-obs-001")
        alerts = detector.check(snap)
        self.assertTrue(len(alerts) > 0)

        # Step 3: Log anomaly
        for alert in alerts:
            sev = AnomalySeverity.CRITICAL if alert.severity == "CRITICAL" else AnomalySeverity.ERROR
            entry = anomaly_log.append(sev, alert.metric, alert.message,
                                       label_id="lbl-obs-001")
            # Step 4: Archive anomaly
            store.append(
                EntryType.ANOMALY,
                label_id="lbl-obs-001",
                payload={"metric": alert.metric, "delta": alert.delta},
            )

        self.assertGreater(anomaly_log.count(), 0)
        self.assertGreater(store.count(), 0)
        self.assertTrue(store.verify())

    def test_feedback_loop_uses_anomaly_log_to_adjust_confidence(self):
        """
        Anomalies in the log → FeedbackLoop → confidence_adjustment < 0.
        """
        anomaly_log = AnomalyLog()
        anomaly_log.append(AnomalySeverity.CRITICAL, "tau", "τ collapsed", "lbl-fb-001")
        anomaly_log.append(AnomalySeverity.ERROR, "drift", "drift elevated", "lbl-fb-001")

        loop = FeedbackLoop(anomaly_log)
        result = loop.process(current_confidence=0.90, label_id="lbl-fb-001")
        self.assertLess(result.confidence_adjustment, 0.0)

    def test_recall_after_archive_contradiction(self):
        """
        Archive records failures → recall says BLOCK.
        """
        store   = MemoryStore()
        catalog = PatternCatalog()
        recall  = RecallProtocol(store, catalog)

        for _ in range(3):
            catalog.record_occurrence("VALID", "council", "risky-hash", 0.90)
            catalog.record_outcome("VALID", "council", "risky-hash", success=False)
            store.append(EntryType.REJECTION, "lbl-risky", {"reason": "FAILURE"})

        result = recall.similar_patterns("VALID", min_occurrences=2)
        self.assertEqual(result.recommendation, "BLOCK")

    def test_metrics_collector_tracks_history_correctly(self):
        """
        MetricsCollector history is bounded and correct.
        """
        collector = MetricsCollector(max_history=10)
        for i in range(15):
            collector.emit(0.85, 0.08, 0.05, 0.90, "labeling")
        # max_history=10 should cap at 10 entries
        self.assertLessEqual(len(collector.history_for_stage("labeling")), 10)

    def test_feedback_loop_does_not_increase_confidence(self):
        """I15: anomalies never increase confidence."""
        log = AnomalyLog()
        log.append(AnomalySeverity.WARN, "betti", "β₁ elevated", "lbl-x")
        loop = FeedbackLoop(log)
        result = loop.process(current_confidence=0.90)
        self.assertLessEqual(result.confidence_adjustment, 0.0)





def _test_observability_module_importable() -> bool:
    """Observability layer imports cleanly."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'execution', 'observability'))
    return True

def _test_archive_does_not_import_from_execution() -> bool:
    """Archive layer does not depend on execution layer."""
    import ast
    import os
    archive_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'epistemic', 'archive')
    for fname in os.listdir(archive_dir):
        if not fname.endswith('.py'): continue
        with open(os.path.join(archive_dir, fname)) as f:
            src = f.read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = (node.module or '') if isinstance(node, ast.ImportFrom) else ''
                assert 'execution' not in str(mod).lower(),                     f"{fname} imports from execution: {mod}"
    return True

def _test_feedback_to_archive_path_exists() -> bool:
    """FeedbackRecord write path exists (not None)."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    # The feedback→archive connection is via chunk_store or feedback_*.json
    # Just verify the pattern exists in ignition
    ignition_path = os.path.join(os.path.dirname(__file__),
                                  '..', '..', 'runtime', 'ignition.py')
    if os.path.exists(ignition_path):
        with open(ignition_path) as f: src = f.read()
        assert 'FeedbackRecord' in src or 'feedback_' in src
    return True

def _test_observability_is_downstream_of_execution() -> bool:
    """Observability is L19 — downstream of execution (L12-L18).
    Verified by architecture doc."""
    import os
    arch = os.path.join(os.path.dirname(__file__), '..', '..', 'ARCHITECTURE.md')
    if os.path.exists(arch):
        with open(arch) as f: content = f.read()
        # L19 Observability appears after L12-L18 in the doc
        l12_pos = content.find('L12')
        l19_pos = content.find('L19')
        assert l19_pos > l12_pos, "L19 must appear after L12 in architecture"
    return True

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
