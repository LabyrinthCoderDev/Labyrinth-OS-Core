"""
tests/epistemic/test_observability.py — Labyrinth-OS
=====================================================
Epistemic pipeline tests: observability layer.

Run with:
    python -m pytest tests/epistemic/test_observability.py -v
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../epistemic/observability"))

from metrics import SystemMetrics, MetricsCollector, TAU_ESCAPE_FLOOR, DRIFT_THRESHOLD
from drift_detector import DriftDetector
from anomaly_log import AnomalyLog, AnomalySeverity
from feedback_loop import FeedbackLoop


class TestObservabilityPipeline(unittest.TestCase):

    def test_healthy_system_shows_ok(self):
        m = SystemMetrics(tau=0.85, chi=0.08, drift=0.05, confidence=0.90, stage="test")
        self.assertEqual(m.health, "OK")

    def test_critical_tau_detected(self):
        m = SystemMetrics(tau=TAU_ESCAPE_FLOOR - 0.01, chi=0.08, drift=0.05,
                          confidence=0.90, stage="test")
        self.assertEqual(m.health, "CRITICAL")

    def test_drift_detector_fires_on_deviation(self):
        detector = DriftDetector()
        detector.update_baseline(tau=0.85, chi=0.08, confidence=0.90)
        snap = SystemMetrics(tau=0.50, chi=0.08, drift=0.05, confidence=0.90, stage="test")
        alerts = detector.check(snap)
        self.assertTrue(any(a.metric == "tau" for a in alerts))

    def test_anomaly_log_append_only(self):
        log = AnomalyLog()
        log.append(AnomalySeverity.WARN, "tau", "test anomaly")
        self.assertFalse(hasattr(log, "delete"))
        self.assertEqual(log.count(), 1)

    def test_feedback_loop_reduces_confidence_on_critical(self):
        log = AnomalyLog()
        for _ in range(3):
            log.append(AnomalySeverity.CRITICAL, "tau", "τ collapsed")
        loop = FeedbackLoop(log)
        result = loop.process(current_confidence=0.90)
        self.assertLess(result.confidence_adjustment, 0.0)
        self.assertTrue(result.demote_flag or not result.promote_flag)

    def test_metrics_collector_tracks_anomalous(self):
        collector = MetricsCollector()
        collector.emit(0.85, 0.08, 0.05, 0.90, "ok")
        collector.emit(0.50, 0.08, 0.05, 0.90, "bad")  # tau below floor
        anomalous = collector.anomalous_snapshots()
        self.assertEqual(len(anomalous), 1)

    def test_feedback_loop_closure_invariant(self):
        """
        I15 — Feedback loop closure: anomalies must reduce confidence, not raise it.
        """
        log = AnomalyLog()
        log.append(AnomalySeverity.ERROR, "drift", "drift detected")
        loop = FeedbackLoop(log)
        result = loop.process(current_confidence=0.90)
        self.assertLessEqual(result.confidence_adjustment, 0.0,
                             "anomalies must not increase confidence")




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
