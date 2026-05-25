"""
gate_binding.py — Labyrinth-OS / Reality Gate (L10.5)
=====================================================
Defines binding rules: what is allowed to cross the Reality Gate?

The binding rules are a policy layer above the gate function.  They enumerate
the exact preconditions required for a label or CGIR edge to be admitted.

References:
  spec/REALITY_GATE.md — Gate binding specification
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, unique
from typing import List, Optional


# ─── BINDING RULE ─────────────────────────────────────────────────────────────

@unique
class BindingRule(str, Enum):
    """Named binding rules checked by GateBinding."""
    MUST_BE_PROMOTED          = "MUST_BE_PROMOTED"
    MUST_HAVE_AUDIT_RECORD    = "MUST_HAVE_AUDIT_RECORD"
    MUST_HAVE_CGIR_PROOF      = "MUST_HAVE_CGIR_PROOF"
    CONFIDENCE_ABOVE_THRESHOLD = "CONFIDENCE_ABOVE_THRESHOLD"
    CATEGORY_MUST_BE_VALID    = "CATEGORY_MUST_BE_VALID"


# ─── BINDING RESULT ───────────────────────────────────────────────────────────

@dataclass
class BindingResult:
    """
    Result of GateBinding.check().

    passed         True if all binding rules passed.
    failed_rules   Rules that were violated.
    notes          Human-readable notes per rule.
    """
    passed:       bool
    failed_rules: List[BindingRule] = field(default_factory=list)
    notes:        List[str]         = field(default_factory=list)


# ─── GATE BINDING ─────────────────────────────────────────────────────────────

class GateBinding:
    """
    Enumerate and enforce the binding rules for Reality Gate entry.

    Usage::

        binding = GateBinding(confidence_threshold=0.85)
        result = binding.check(
            promoted=True,
            has_audit_record=True,
            has_cgir_proof=True,
            confidence=0.92,
            category="VALID",
        )
        print(result.passed)   # True
    """

    DEFAULT_CONFIDENCE_THRESHOLD: float = 0.85

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        self._threshold = confidence_threshold

    def check(
        self,
        promoted: bool,
        has_audit_record: bool,
        has_cgir_proof: bool,
        confidence: float,
        category: str,
    ) -> BindingResult:
        """
        Check all binding rules.

        Parameters
        ----------
        promoted           Was this label APPROVED by the promotion pipeline?
        has_audit_record   Does an AuditRecord exist for this label?
        has_cgir_proof     Does a valid CGIR proof exist for this edge?
        confidence         Current confidence score [0, 1].
        category           LabelCategory string (must be "VALID").

        Returns
        -------
        BindingResult — passed=True only if all rules pass.
        """
        failed: List[BindingRule] = []
        notes:  List[str]         = []

        if not promoted:
            failed.append(BindingRule.MUST_BE_PROMOTED)
            notes.append("label not approved by promotion pipeline")

        if not has_audit_record:
            failed.append(BindingRule.MUST_HAVE_AUDIT_RECORD)
            notes.append("no audit record found for this label")

        if not has_cgir_proof:
            failed.append(BindingRule.MUST_HAVE_CGIR_PROOF)
            notes.append("no CGIR proof attached to this edge")

        if confidence < self._threshold:
            failed.append(BindingRule.CONFIDENCE_ABOVE_THRESHOLD)
            notes.append(
                f"confidence {confidence:.3f} < threshold {self._threshold:.3f}"
            )

        if category != "VALID":
            failed.append(BindingRule.CATEGORY_MUST_BE_VALID)
            notes.append(f"category must be VALID, got {category!r}")

        return BindingResult(
            passed=len(failed) == 0,
            failed_rules=failed,
            notes=notes,
        )

    def all_rules(self) -> List[BindingRule]:
        """Return the complete set of binding rules."""
        return list(BindingRule)




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_binding_constructs() -> bool:
    gb = GateBinding(); assert gb is not None; return True

def _test_all_checks_pass() -> bool:
    gb = GateBinding(confidence_threshold=0.85)
    result = gb.check(promoted=True, has_audit_record=True,
                       has_cgir_proof=True, confidence=0.95, category="VALID")
    assert result.passed, f"Expected pass: {result.notes}"; return True

def _test_not_promoted_fails() -> bool:
    gb = GateBinding()
    result = gb.check(promoted=False, has_audit_record=True,
                       has_cgir_proof=True, confidence=0.95, category="VALID")
    assert not result.passed; return True

def _test_low_confidence_fails() -> bool:
    gb = GateBinding(confidence_threshold=0.85)
    result = gb.check(promoted=True, has_audit_record=True,
                       has_cgir_proof=True, confidence=0.30, category="VALID")
    assert not result.passed; return True

def _test_missing_audit_fails() -> bool:
    gb = GateBinding()
    result = gb.check(promoted=True, has_audit_record=False,
                       has_cgir_proof=True, confidence=0.95, category="VALID")
    assert not result.passed; return True

def _test_all_rules_returns_list() -> bool:
    gb = GateBinding()
    rules = gb.all_rules()
    assert isinstance(rules, list) and len(rules) > 0; return True



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
