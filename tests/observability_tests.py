"""
observability_tests.py — Labyrinth-OS / Observability Layer (L5.75)
====================================================================
Unit tests for the observability layer.

Run with:
    python -m pytest epistemic/observability/observability_tests.py -v
"""

from __future__ import annotations

import time
import unittest

from metrics import (
    SystemMetrics,
    MetricsCollector,
    TAU_ESCAPE_FLOOR,
    CHI_WARN,
    CHI_COLLAPSE,
    DRIFT_THRESHOLD,
)
from drift_detector import DriftDetector, DriftAlert
from anomaly_log import AnomalyLog, AnomalyEntry, AnomalySeverity
from feedback_loop import FeedbackLoop, FeedbackResult


# ─── METRICS TESTS ────────────────────────────────────────────────────────────

class TestSystemMetrics(unittest.TestCase):

    def _make(self, **kw) -> SystemMetrics:
        defaults = dict(tau=0.85, chi=0.08, drift=0.05, confidence=0.90, stage="test")
        defaults.update(kw)
        return SystemMetrics(**defaults)

    def test_ok_health(self):
        m = self._make()
        self.assertEqual(m.health, "OK")

    def test_critical_on_low_tau(self):
        m = self._make(tau=TAU_ESCAPE_FLOOR - 0.01)
        self.assertEqual(m.health, "CRITICAL")

    def test_critical_on_chi_collapse(self):
        m = self._make(chi=CHI_COLLAPSE + 0.01)
        self.assertEqual(m.health, "CRITICAL")

    def test_warn_on_chi_warn(self):
        m = self._make(chi=CHI_WARN + 0.01)
        self.assertEqual(m.health, "WARN")

    def test_error_on_drift_threshold(self):
        m = self._make(drift=DRIFT_THRESHOLD + 0.01)
        self.assertEqual(m.health, "ERROR")

    def test_error_on_betti_cap(self):
        from metrics import BETTI_1_CAP
        m = self._make(betti_1=BETTI_1_CAP + 0.001)
        self.assertEqual(m.health, "ERROR")


class TestMetricsCollector(unittest.TestCase):

    def setUp(self):
        self.collector = MetricsCollector()

    def test_emit_returns_snapshot(self):
        m = self.collector.emit(0.85, 0.08, 0.05, 0.90, "labeling")
        self.assertIsInstance(m, SystemMetrics)

    def test_latest_after_emit(self):
        self.collector.emit(0.85, 0.08, 0.05, 0.90, "labeling")
        self.assertIsNotNone(self.collector.latest)

    def test_latest_none_on_empty(self):
        self.assertIsNone(self.collector.latest)

    def test_history_for_stage(self):
        self.collector.emit(0.85, 0.08, 0.05, 0.90, "labeling")
        self.collector.emit(0.80, 0.10, 0.06, 0.88, "promotion")
        self.assertEqual(len(self.collector.history_for_stage("labeling")), 1)
        self.assertEqual(len(self.collector.history_for_stage("promotion")), 1)

    def test_mean_confidence(self):
        self.collector.emit(0.85, 0.08, 0.05, 1.0, "labeling")
        self.collector.emit(0.85, 0.08, 0.05, 0.8, "labeling")
        self.assertAlmostEqual(self.collector.mean_confidence(), 0.9)

    def test_anomalous_snapshots(self):
        self.collector.emit(0.85, 0.08, 0.05, 0.90, "ok-stage")
        self.collector.emit(0.50, 0.08, 0.05, 0.90, "bad-stage")  # tau below floor
        anom = self.collector.anomalous_snapshots()
        self.assertEqual(len(anom), 1)

    def test_values_clamped(self):
        m = self.collector.emit(2.0, -1.0, 0.05, 0.90, "test")
        self.assertEqual(m.tau, 1.0)
        self.assertEqual(m.chi, 0.0)


# ─── DRIFT DETECTOR TESTS ────────────────────────────────────────────────────

class TestDriftDetector(unittest.TestCase):

    def setUp(self):
        self.detector = DriftDetector()
        self.detector.update_baseline(tau=0.85, chi=0.08, confidence=0.90)

    def _snap(self, **kw) -> SystemMetrics:
        defaults = dict(tau=0.85, chi=0.08, drift=0.05, confidence=0.90, stage="test")
        defaults.update(kw)
        return SystemMetrics(**defaults)

    def test_no_alert_on_baseline(self):
        alerts = self.detector.check(self._snap())
        self.assertEqual(alerts, [])

    def test_alert_on_tau_drift(self):
        snap = self._snap(tau=0.85 - DRIFT_THRESHOLD - 0.01)
        alerts = self.detector.check(snap)
        self.assertTrue(any(a.metric == "tau" for a in alerts))

    def test_alert_on_confidence_drift(self):
        snap = self._snap(confidence=0.90 - DRIFT_THRESHOLD - 0.01)
        alerts = self.detector.check(snap)
        self.assertTrue(any(a.metric == "confidence" for a in alerts))

    def test_alert_count_accumulates(self):
        for _ in range(3):
            self.detector.check(self._snap(tau=0.0))
        self.assertGreater(self.detector.alert_count(), 0)

    def test_recent_alerts_limit(self):
        for _ in range(25):
            self.detector.check(self._snap(tau=0.0))
        self.assertLessEqual(len(self.detector.recent_alerts(limit=10)), 10)

    def test_critical_severity_on_large_delta(self):
        snap = self._snap(tau=0.0)  # delta = 0.85 >> 2 * DRIFT_THRESHOLD
        alerts = self.detector.check(snap)
        tau_alerts = [a for a in alerts if a.metric == "tau"]
        self.assertTrue(any(a.severity == "CRITICAL" for a in tau_alerts))


# ─── ANOMALY LOG TESTS ────────────────────────────────────────────────────────

class TestAnomalyLog(unittest.TestCase):

    def setUp(self):
        self.log = AnomalyLog()

    def test_append_returns_entry(self):
        entry = self.log.append(AnomalySeverity.WARN, "tau", "τ dropped")
        self.assertIsInstance(entry, AnomalyEntry)
        self.assertEqual(entry.anomaly_id, 1)

    def test_sequential_ids(self):
        for _ in range(5):
            e = self.log.append(AnomalySeverity.WARN, "chi", "χ elevated")
        self.assertEqual(e.anomaly_id, 5)

    def test_has_critical_false_when_empty(self):
        self.assertFalse(self.log.has_critical)

    def test_has_critical_true(self):
        self.log.append(AnomalySeverity.CRITICAL, "tau", "τ collapse")
        self.assertTrue(self.log.has_critical)

    def test_count_all(self):
        self.log.append(AnomalySeverity.WARN, "tau", "warn")
        self.log.append(AnomalySeverity.ERROR, "chi", "error")
        self.assertEqual(self.log.count(), 2)

    def test_count_by_severity(self):
        self.log.append(AnomalySeverity.WARN, "tau", "warn")
        self.log.append(AnomalySeverity.CRITICAL, "tau", "critical")
        self.assertEqual(self.log.count(AnomalySeverity.CRITICAL), 1)

    def test_query_by_label_id(self):
        self.log.append(AnomalySeverity.WARN, "tau", "a", label_id="lbl-001")
        self.log.append(AnomalySeverity.WARN, "chi", "b", label_id="lbl-002")
        results = self.log.query(label_id="lbl-001")
        self.assertEqual(len(results), 1)

    def test_latest_returns_last_entry(self):
        self.log.append(AnomalySeverity.WARN, "tau", "first")
        self.log.append(AnomalySeverity.ERROR, "chi", "last")
        self.assertEqual(self.log.latest().description, "last")

    def test_append_only_no_delete(self):
        self.assertFalse(hasattr(self.log, "delete"))
        self.assertFalse(hasattr(self.log, "remove"))


# ─── FEEDBACK LOOP TESTS ─────────────────────────────────────────────────────

class TestFeedbackLoop(unittest.TestCase):

    def setUp(self):
        self.log = AnomalyLog()
        self.loop = FeedbackLoop(self.log)

    def test_no_anomalies_no_adjustment(self):
        result = self.loop.process(current_confidence=0.90)
        self.assertEqual(result.anomalies_processed, 0)
        self.assertAlmostEqual(result.confidence_adjustment, 0.0)
        self.assertFalse(result.demote_flag)

    def test_critical_anomaly_reduces_confidence(self):
        self.log.append(AnomalySeverity.CRITICAL, "tau", "collapse")
        result = self.loop.process(current_confidence=0.90)
        self.assertLess(result.confidence_adjustment, 0.0)

    def test_multiple_criticals_cause_demotion(self):
        for _ in range(5):
            self.log.append(AnomalySeverity.CRITICAL, "tau", "collapse")
        result = self.loop.process(current_confidence=0.88)
        self.assertTrue(result.demote_flag)

    def test_promote_flag_when_high_confidence_and_no_anomalies(self):
        result = self.loop.process(current_confidence=0.90)
        self.assertTrue(result.promote_flag)

    def test_per_label_filtering(self):
        self.log.append(AnomalySeverity.CRITICAL, "tau", "for lbl-001", label_id="lbl-001")
        self.log.append(AnomalySeverity.WARN, "chi", "for lbl-002", label_id="lbl-002")
        result = self.loop.process(current_confidence=0.90, label_id="lbl-001")
        self.assertEqual(result.anomalies_processed, 1)

    def test_notes_populated_on_anomalies(self):
        self.log.append(AnomalySeverity.CRITICAL, "tau", "collapse")
        result = self.loop.process(current_confidence=0.90)
        self.assertGreater(len(result.notes), 0)

    def test_critical_anomaly_count(self):
        self.log.append(AnomalySeverity.CRITICAL, "tau", "c1")
        self.log.append(AnomalySeverity.WARN, "chi", "w1")
        self.assertEqual(self.loop.critical_anomaly_count(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


def run_tests() -> tuple:
    """Labyrinth-OS standard test runner wrapper for run_all.py compatibility."""
    import unittest
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [TestSystemMetrics, TestDriftDetector, TestAnomalyLog, TestFeedbackLoop]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(stream=__import__('io').StringIO(), verbosity=0)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    results = []
    for test, _ in result.failures:
        results.append((str(test), "FAIL", "assertion failed"))
    for test, _ in result.errors:
        results.append((str(test), "FAIL", "error"))
    for i in range(passed):
        results.append((f"test_{i}", "PASS", None))
    return passed, failed, results


if __name__ == "__main__":
    import unittest
    unittest.main()
