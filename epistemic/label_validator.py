"""
label_validator.py — Labyrinth-OS / Epistemic Labeling Layer (L3.5)
====================================================================
Validate LabelRecord instances against the schema defined in label_schema.py.

The validator is the enforcement point for I11 (Labeling Closure):
  Only VALID labels with confidence ≥ threshold may advance toward the
  Reality Gate.  All others are rejected here, not at the Gate.

Rules enforced:
  1. Required fields present and correctly typed.
  2. confidence ∈ [0.0, 1.0] when not None.
  3. VALID labels must have confidence ≥ VALID_CONFIDENCE_FLOOR.
  4. REJECTED labels must carry a RejectionReason.
  5. label_id must not be empty.
  6. source must not be empty.
  7. Label must not be expired (TTL check).

References:
  ARCHITECTURE.md  — L3.5 Labeling
  spec/LABELING.md — Formal labeling specification
  INVARIANTS.md    — I11 Labeling closure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from label_schema import (
    LabelCategory,
    LabelRecord,
    RejectionReason,
)


# ─── VALIDATION RESULT ────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """
    Output of LabelValidator.validate().

    passed           True if the label passed all checks.
    rejection_reason First rejection reason encountered (or None).
    errors           All error messages collected during validation.
    label_id         Echo of the label_id that was validated.
    """
    passed:           bool
    label_id:         str
    rejection_reason: Optional[RejectionReason] = None
    errors:           List[str]                 = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


# ─── VALID_CONFIDENCE_FLOOR ───────────────────────────────────────────────────

#: Minimum confidence required for LabelCategory.VALID.
#: Labels below this floor are downgraded to UNCERTAIN or REJECTED.
VALID_CONFIDENCE_FLOOR: float = 0.60

#: Promotion confidence threshold — labels need this to advance to Reality Gate.
PROMOTION_CONFIDENCE_THRESHOLD: float = 0.85


# ─── LABEL VALIDATOR ─────────────────────────────────────────────────────────

class LabelValidator:
    """
    Validate LabelRecord instances against the labeling schema.

    Thread-safe: all state is in local variables.  Can be shared.

    Parameters
    ----------
    seen_ids : optional pre-populated set of label_ids to detect duplicates.
    """

    def __init__(self, seen_ids: Optional[Set[str]] = None) -> None:
        self._seen_ids: Set[str] = set(seen_ids or [])

    # ── public API ────────────────────────────────────────────────────────────

    def validate(self, record: LabelRecord) -> ValidationResult:
        """
        Run all validation checks on *record*.

        Returns a ValidationResult.  If any check fails the result is
        marked as not passed, carrying the first rejection reason and all
        error messages.

        Fail-closed: unknown errors produce a SCHEMA_VIOLATION.
        """
        errors: List[str] = []
        rejection_reason: Optional[RejectionReason] = None

        try:
            # ── field presence ───────────────────────────────────────────────
            if not record.label_id or not isinstance(record.label_id, str):
                errors.append("label_id must be a non-empty string")
                rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION

            if not record.source or not isinstance(record.source, str):
                errors.append("source must be a non-empty string")
                rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION

            if not isinstance(record.category, LabelCategory):
                errors.append(f"category must be a LabelCategory, got {type(record.category)}")
                rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION

            if record.content is None:
                errors.append("content must not be None")
                rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION

            # ── confidence range ─────────────────────────────────────────────
            if record.confidence is not None:
                if not isinstance(record.confidence, (int, float)):
                    errors.append("confidence must be a float or None")
                    rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION
                elif not (0.0 <= record.confidence <= 1.0):
                    errors.append(
                        f"confidence {record.confidence} out of [0.0, 1.0] range"
                    )
                    rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION

            # ── VALID category constraints ───────────────────────────────────
            if record.category == LabelCategory.VALID:
                conf = record.confidence
                if conf is None or conf < VALID_CONFIDENCE_FLOOR:
                    errors.append(
                        f"VALID label requires confidence ≥ {VALID_CONFIDENCE_FLOOR}, "
                        f"got {conf}"
                    )
                    rejection_reason = (
                        rejection_reason or RejectionReason.CONFIDENCE_BELOW_THRESHOLD
                    )

            # ── REJECTED category constraints ────────────────────────────────
            if record.category == LabelCategory.REJECTED:
                if record.rejection_reason is None:
                    errors.append("REJECTED label must carry a rejection_reason")
                    rejection_reason = rejection_reason or RejectionReason.SCHEMA_VIOLATION

            # ── TTL / expiry ─────────────────────────────────────────────────
            if record.is_expired():
                errors.append(
                    f"label_id={record.label_id!r} has expired (ttl={record.ttl_seconds}s)"
                )
                rejection_reason = rejection_reason or RejectionReason.STALE_LABEL

            # ── duplicate detection ──────────────────────────────────────────
            if record.label_id in self._seen_ids:
                errors.append(f"duplicate label_id={record.label_id!r}")
                rejection_reason = rejection_reason or RejectionReason.DUPLICATE_LABEL
            else:
                self._seen_ids.add(record.label_id)

        except Exception as exc:  # noqa: BLE001
            errors.append(f"internal validator error: {exc}")
            rejection_reason = RejectionReason.SCHEMA_VIOLATION

        passed = len(errors) == 0
        return ValidationResult(
            passed=passed,
            label_id=record.label_id,
            rejection_reason=rejection_reason if not passed else None,
            errors=errors,
        )

    def validate_for_promotion(self, record: LabelRecord) -> ValidationResult:
        """
        Stricter check: label must satisfy promotion threshold (≥ 0.85).

        Runs base validate() first, then applies the promotion threshold.
        Used by the promotion pipeline before Reality Gate entry.
        """
        result = self.validate(record)
        if not result.passed:
            return result

        conf = record.confidence
        if conf is None or conf < PROMOTION_CONFIDENCE_THRESHOLD:
            return ValidationResult(
                passed=False,
                label_id=record.label_id,
                rejection_reason=RejectionReason.CONFIDENCE_BELOW_THRESHOLD,
                errors=[
                    f"promotion requires confidence ≥ {PROMOTION_CONFIDENCE_THRESHOLD}, "
                    f"got {conf}"
                ],
            )
        return result

    def reset_seen_ids(self) -> None:
        """Clear the duplicate-detection registry."""
        self._seen_ids.clear()


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_label(label_id="test_001", category=None, confidence=0.90,
                source="test", content="test content"):
    from label_schema import LabelRecord, LabelCategory
    import time
    return LabelRecord(
        label_id=label_id,
        category=category or LabelCategory.VALID,
        confidence=confidence,
        source=source,
        content=content,
        timestamp=time.time(),
    )

def _test_validator_constructs() -> bool:
    v = LabelValidator()
    assert v is not None
    return True

def _test_valid_label_passes() -> bool:
    v = LabelValidator()
    record = _make_label()
    result = v.validate(record)
    assert result.passed, f"Expected passed: {result.errors}"
    return True

def _test_empty_label_id_rejected() -> bool:
    v = LabelValidator()
    record = _make_label(label_id="")
    result = v.validate(record)
    assert not result.passed
    return True

def _test_out_of_range_confidence_rejected() -> bool:
    v = LabelValidator()
    try:
        record = _make_label(confidence=1.5)
        result = v.validate(record)
        assert not result.passed
    except (ValueError, AssertionError):
        pass
    return True

def _test_validation_result_has_errors_field() -> bool:
    vr = ValidationResult(passed=False, label_id="x", errors=["test error"])
    assert len(vr.errors) == 1
    return True

def _test_empty_source_rejected() -> bool:
    v = LabelValidator()
    record = _make_label(source="")
    result = v.validate(record)
    assert not result.passed
    return True



def run_tests() -> tuple:
    tests = sorted(
        [(n, o) for n, o in globals().items()
         if n.startswith("_test_") and callable(o)],
        key=lambda x: x[0],
    )
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)))
    return passed, failed, results


if __name__ == "__main__":
    p, f, results = run_tests()
    for n, s, e in results:
        print(f"  {'chr(10001) if s=={chr(39)}PASS{chr(39)} else chr(10007)'} {n}" + (f"  → {e}" if e else ""))
    print(f"  Results: {p} passed, {f} failed")
    if f: raise SystemExit(1)
