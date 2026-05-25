"""
labeling_tests.py — Labyrinth-OS / Epistemic Labeling Layer (L3.5)
===================================================================
Unit tests for the labeling layer.

Tests cover:
  - Label schema (categories, tiers, rejection reasons)
  - LabelRecord construction, hashing, and expiry
  - LabelValidator (base checks + promotion checks)
  - ConfidenceMeter (scoring, decay, trend detection)

Run with:
    python -m pytest epistemic/labeling/labeling_tests.py -v
"""

from __future__ import annotations

import time
import unittest

from label_schema import (
    LabelCategory,
    ConfidenceTier,
    RejectionReason,
    LabelRecord,
)
from label_validator import (
    LabelValidator,
    ValidationResult,
    VALID_CONFIDENCE_FLOOR,
    PROMOTION_CONFIDENCE_THRESHOLD,
)
from confidence_meter import (
    ConfidenceMeter,
    DECLINE_THRESHOLD,
    WINDOW_SIZE,
)


# ─── LABEL RECORD TESTS ───────────────────────────────────────────────────────

class TestLabelRecord(unittest.TestCase):

    def _make(self, **kw) -> LabelRecord:
        defaults = dict(
            label_id="lbl-001",
            category=LabelCategory.VALID,
            confidence=0.90,
            source="council",
            content="proposal-hash-abc123",
        )
        defaults.update(kw)
        return LabelRecord(**defaults)

    def test_valid_label_creates_successfully(self):
        rec = self._make()
        self.assertEqual(rec.category, LabelCategory.VALID)
        self.assertEqual(rec.confidence, 0.90)

    def test_seal_hash_is_deterministic(self):
        rec = self._make()
        self.assertEqual(rec.seal_hash(), rec.seal_hash())

    def test_seal_hash_changes_with_content(self):
        rec1 = self._make(content="aaa")
        rec2 = self._make(content="bbb")
        self.assertNotEqual(rec1.seal_hash(), rec2.seal_hash())

    def test_not_expired_when_ttl_zero(self):
        rec = self._make(ttl_seconds=0)
        self.assertFalse(rec.is_expired())

    def test_expired_when_ttl_exceeded(self):
        rec = self._make(ttl_seconds=1, timestamp=time.time() - 10)
        self.assertTrue(rec.is_expired())

    def test_not_expired_when_within_ttl(self):
        rec = self._make(ttl_seconds=3600)
        self.assertFalse(rec.is_expired())

    def test_confidence_tier_high(self):
        rec = self._make(confidence=0.90)
        self.assertEqual(rec.confidence_tier(), ConfidenceTier.HIGH)

    def test_confidence_tier_medium(self):
        rec = self._make(confidence=0.70)
        self.assertEqual(rec.confidence_tier(), ConfidenceTier.MEDIUM)

    def test_confidence_tier_low(self):
        rec = self._make(confidence=0.40)
        self.assertEqual(rec.confidence_tier(), ConfidenceTier.LOW)

    def test_confidence_tier_uninitialized_on_none(self):
        rec = self._make(confidence=None, category=LabelCategory.UNCERTAIN)
        self.assertEqual(rec.confidence_tier(), ConfidenceTier.UNINITIALIZED)

    def test_confidence_tier_uninitialized_below_floor(self):
        rec = self._make(confidence=0.10, category=LabelCategory.UNCERTAIN)
        self.assertEqual(rec.confidence_tier(), ConfidenceTier.UNINITIALIZED)


# ─── LABEL VALIDATOR TESTS ────────────────────────────────────────────────────

class TestLabelValidator(unittest.TestCase):

    def setUp(self):
        self.validator = LabelValidator()

    def _make(self, **kw) -> LabelRecord:
        defaults = dict(
            label_id="lbl-v-001",
            category=LabelCategory.VALID,
            confidence=0.90,
            source="council",
            content="some-proposal",
        )
        defaults.update(kw)
        return LabelRecord(**defaults)

    # ── passing cases ─────────────────────────────────────────────────────────

    def test_valid_label_passes(self):
        result = self.validator.validate(self._make())
        self.assertTrue(result.passed)
        self.assertIsNone(result.rejection_reason)

    def test_uncertain_with_no_confidence_passes(self):
        rec = self._make(
            label_id="lbl-v-002",
            category=LabelCategory.UNCERTAIN,
            confidence=None,
        )
        result = self.validator.validate(rec)
        self.assertTrue(result.passed)

    def test_rejected_with_reason_passes_schema(self):
        rec = self._make(
            label_id="lbl-v-003",
            category=LabelCategory.REJECTED,
            confidence=0.20,
            rejection_reason=RejectionReason.CONFIDENCE_BELOW_THRESHOLD,
        )
        result = self.validator.validate(rec)
        self.assertTrue(result.passed)

    # ── failing cases ─────────────────────────────────────────────────────────

    def test_empty_label_id_fails(self):
        rec = self._make(label_id="")
        result = self.validator.validate(rec)
        self.assertFalse(result.passed)
        self.assertEqual(result.rejection_reason, RejectionReason.SCHEMA_VIOLATION)

    def test_empty_source_fails(self):
        rec = self._make(label_id="lbl-v-004", source="")
        result = self.validator.validate(rec)
        self.assertFalse(result.passed)

    def test_confidence_out_of_range_fails(self):
        rec = self._make(label_id="lbl-v-005", confidence=1.5)
        result = self.validator.validate(rec)
        self.assertFalse(result.passed)

    def test_valid_category_with_low_confidence_fails(self):
        rec = self._make(
            label_id="lbl-v-006",
            category=LabelCategory.VALID,
            confidence=VALID_CONFIDENCE_FLOOR - 0.01,
        )
        result = self.validator.validate(rec)
        self.assertFalse(result.passed)
        self.assertEqual(
            result.rejection_reason, RejectionReason.CONFIDENCE_BELOW_THRESHOLD
        )

    def test_rejected_without_reason_fails(self):
        rec = self._make(
            label_id="lbl-v-007",
            category=LabelCategory.REJECTED,
            confidence=0.10,
            rejection_reason=None,
        )
        result = self.validator.validate(rec)
        self.assertFalse(result.passed)

    def test_expired_label_fails(self):
        rec = self._make(
            label_id="lbl-v-008",
            ttl_seconds=1,
            timestamp=time.time() - 100,
        )
        result = self.validator.validate(rec)
        self.assertFalse(result.passed)
        self.assertEqual(result.rejection_reason, RejectionReason.STALE_LABEL)

    def test_duplicate_label_id_fails(self):
        rec1 = self._make(label_id="lbl-dup")
        rec2 = self._make(label_id="lbl-dup")
        self.validator.validate(rec1)
        result = self.validator.validate(rec2)
        self.assertFalse(result.passed)
        self.assertEqual(result.rejection_reason, RejectionReason.DUPLICATE_LABEL)

    def test_reset_clears_seen_ids(self):
        rec = self._make(label_id="lbl-reset")
        self.validator.validate(rec)
        self.validator.reset_seen_ids()
        result = self.validator.validate(self._make(label_id="lbl-reset"))
        self.assertTrue(result.passed)

    # ── promotion validation ──────────────────────────────────────────────────

    def test_promotion_passes_with_high_confidence(self):
        rec = self._make(
            label_id="lbl-promo-ok",
            confidence=PROMOTION_CONFIDENCE_THRESHOLD + 0.01,
        )
        result = self.validator.validate_for_promotion(rec)
        self.assertTrue(result.passed)

    def test_promotion_fails_with_medium_confidence(self):
        rec = self._make(
            label_id="lbl-promo-fail",
            confidence=PROMOTION_CONFIDENCE_THRESHOLD - 0.01,
        )
        result = self.validator.validate_for_promotion(rec)
        self.assertFalse(result.passed)
        self.assertEqual(
            result.rejection_reason, RejectionReason.CONFIDENCE_BELOW_THRESHOLD
        )

    def test_promotion_inherits_base_failures(self):
        rec = self._make(label_id="", confidence=0.99)
        result = self.validator.validate_for_promotion(rec)
        self.assertFalse(result.passed)


# ─── CONFIDENCE METER TESTS ──────────────────────────────────────────────────

class TestConfidenceMeter(unittest.TestCase):

    def setUp(self):
        self.meter = ConfidenceMeter()

    def test_compute_weighted_score(self):
        sample = self.meter.compute(
            label_id="lbl-cm-001",
            sensor_agreement=1.0,
            historical_success=1.0,
            temporal_consistency=1.0,
        )
        self.assertAlmostEqual(sample.score, 1.0)

    def test_compute_zero_score(self):
        sample = self.meter.compute(
            label_id="lbl-cm-002",
            sensor_agreement=0.0,
            historical_success=0.0,
            temporal_consistency=0.0,
        )
        self.assertAlmostEqual(sample.score, 0.0)

    def test_compute_weighted_composite(self):
        # 0.4*0.8 + 0.35*0.6 + 0.25*0.4 = 0.32 + 0.21 + 0.10 = 0.63
        sample = self.meter.compute(
            label_id="lbl-cm-003",
            sensor_agreement=0.8,
            historical_success=0.6,
            temporal_consistency=0.4,
        )
        self.assertAlmostEqual(sample.score, 0.63, places=5)

    def test_invalid_component_raises(self):
        with self.assertRaises(ValueError):
            self.meter.compute("x", sensor_agreement=1.5,
                               historical_success=0.5, temporal_consistency=0.5)

    def test_rolling_mean_none_when_empty(self):
        self.assertIsNone(self.meter.rolling_mean())

    def test_rolling_mean_after_samples(self):
        for _ in range(4):
            self.meter.compute("x", 0.8, 0.8, 0.8)
        mean = self.meter.rolling_mean()
        self.assertIsNotNone(mean)
        self.assertGreater(mean, 0.0)

    def test_not_declining_with_stable_scores(self):
        for _ in range(10):
            self.meter.compute("x", 0.9, 0.9, 0.9)
        self.assertFalse(self.meter.is_declining())

    def test_declining_detected(self):
        # Fill old half with high scores
        for _ in range(10):
            self.meter.compute("x", 0.9, 0.9, 0.9)
        # Fill new half with low scores
        for _ in range(10):
            self.meter.compute("x", 0.1, 0.1, 0.1)
        self.assertTrue(self.meter.is_declining())

    def test_decay_reduces_score(self):
        # Compute without decay
        base = self.meter.compute("x", 0.8, 0.8, 0.8)
        self.meter.reset()
        # Compute with decay (pretend it was computed 1000s ago)
        decayed = self.meter.compute_with_decay(
            "x", 0.8, 0.8, 0.8, last_computed_at=time.time() - 1000
        )
        self.assertLess(decayed.score, base.score)

    def test_reset_clears_window(self):
        self.meter.compute("x", 0.8, 0.8, 0.8)
        self.meter.reset()
        self.assertIsNone(self.meter.rolling_mean())

    def test_window_bounded(self):
        for i in range(WINDOW_SIZE + 10):
            self.meter.compute(f"x{i}", 0.8, 0.8, 0.8)
        self.assertLessEqual(len(self.meter.recent_scores()), WINDOW_SIZE)


# ─── SCHEMA ENFORCEMENT TESTS ─────────────────────────────────────────────────

class TestSchemaEnforcement(unittest.TestCase):
    """End-to-end tests that enforce the labeling schema invariants."""

    def test_only_valid_category_can_have_valid_in_name(self):
        """All LabelCategory values are enumerated — no unknowns."""
        known = {c.value for c in LabelCategory}
        self.assertIn("VALID", known)
        self.assertIn("UNCERTAIN", known)
        self.assertIn("REJECTED", known)
        self.assertIn("DEFERRED", known)

    def test_rejection_reasons_are_enumerated(self):
        """All RejectionReason values are enumerated."""
        known = {r.value for r in RejectionReason}
        self.assertIn("SCHEMA_VIOLATION", known)
        self.assertIn("CONFIDENCE_BELOW_THRESHOLD", known)
        self.assertIn("POLICY_VIOLATION", known)

    def test_valid_category_always_needs_confidence(self):
        """VALID labels must have numeric confidence ≥ floor."""
        validator = LabelValidator()
        rec = LabelRecord(
            label_id="schema-test-001",
            category=LabelCategory.VALID,
            confidence=None,
            source="test",
            content="x",
        )
        result = validator.validate(rec)
        self.assertFalse(result.passed)

    def test_deferred_label_passes_without_rejection_reason(self):
        """DEFERRED is structurally valid even without rejection_reason."""
        validator = LabelValidator()
        rec = LabelRecord(
            label_id="schema-test-002",
            category=LabelCategory.DEFERRED,
            confidence=0.50,
            source="test",
            content="x",
        )
        result = validator.validate(rec)
        self.assertTrue(result.passed)



def run_tests() -> tuple:
    """Labyrinth-OS standard runner — wraps unittest for run_all.py compatibility."""
    import unittest, io
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    buf    = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    result = runner.run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    results = []
    for test, tb in result.failures + result.errors:
        results.append((str(test), "FAIL", tb.split("\n")[-2]))
    for i in range(passed):
        results.append((f"test_{i:03}", "PASS", None))
    return passed, failed, results


if __name__ == "__main__":
    import unittest
    unittest.main()
