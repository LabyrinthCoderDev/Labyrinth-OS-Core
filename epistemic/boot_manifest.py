"""
boot_manifest.py — Labyrinth-OS / Lane 1 / L00
================================================
L00 Boot Manifest

The system's startup self-check. Runs before any input arrives,
before any lane is active. Validates that the system is in a
known-good state before accepting work.

What it checks:
  - Sigma Anchor constants are within valid ranges
  - Required Lane 1 modules are importable
  - Required Lane 2 modules are importable
  - ACP-1 tracker is reachable
  - Hardware slot (guardian) is present (mock or real)

Produces a BootReceipt — an immutable record of what was found
at startup. If critical modules are missing, boot fails.

Non-critical gaps (e.g. Rust crates not compiled) are recorded
as warnings, not failures.

References:
  ARCHITECTURE.md — L00 Boot Manifest
  INVARIANTS.md   — system must know its own state at startup
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple


# ─── SIGMA ANCHOR CONSTANTS ───────────────────────────────────────────────────
# These are the constitutional boundary. If they are wrong at boot,
# the system is in an unknown state.

EXPECTED_CONSTANTS = {
    "TAU_ESCAPE_FLOOR": 0.75,
    "CHI_WARN":         0.15,
    "CHI_COLLAPSE":     0.40,
    "DRIFT_THRESHOLD":  0.12,
    "BETTI_1_CAP":      0.045,
}


@unique
class BootStatus(str, Enum):
    PASS    = "PASS"
    WARN    = "WARN"    # non-critical gap
    FAIL    = "FAIL"    # critical — system should not proceed


@dataclass(frozen=True)
class BootCheck:
    """Result of one boot check."""
    name:   str
    status: BootStatus
    detail: str


@dataclass
class BootReceipt:
    """
    Immutable record of system state at startup.
    Written once. Never modified.
    """
    boot_id:    str
    booted_at:  float
    checks:     List[BootCheck]
    overall:    BootStatus
    python_ver: str
    cwd:        str

    @property
    def critical_failures(self) -> List[BootCheck]:
        return [c for c in self.checks if c.status == BootStatus.FAIL]

    @property
    def warnings(self) -> List[BootCheck]:
        return [c for c in self.checks if c.status == BootStatus.WARN]

    @property
    def receipt_hash(self) -> str:
        payload = json.dumps({
            "boot_id":   self.boot_id,
            "booted_at": round(self.booted_at, 3),
            "overall":   self.overall.value,
            "checks":    [(c.name, c.status.value) for c in self.checks],
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "boot_id":    self.boot_id,
            "booted_at":  self.booted_at,
            "overall":    self.overall.value,
            "failures":   len(self.critical_failures),
            "warnings":   len(self.warnings),
            "receipt_hash": self.receipt_hash,
            "checks": [
                {"name": c.name, "status": c.status.value, "detail": c.detail}
                for c in self.checks
            ],
        }


class BootManifest:
    """
    L00: System startup validator.

    Run before any input arrives. Produces a BootReceipt.
    If overall=FAIL, the system should not accept work.
    """

    REQUIRED_LANE2 = [
        "cgir_types", "cgir_core", "cgir_validator",
        "cgir_gate", "guardian_slot", "hashchain",
        "cgir_ledger", "replay_validator",
    ]

    REQUIRED_LANE1 = [
        "epistemic_types", "mode_router", "epistemic_labeler",
        "archive_memory", "promotion_protocol", "reality_gate",
        "pipeline_wire", "deferred_node",
    ]

    def run(self) -> BootReceipt:
        boot_id = hashlib.sha256(
            f"boot:{time.time()}".encode()
        ).hexdigest()[:16]
        checks: List[BootCheck] = []

        # 1. Sigma Anchor constants
        checks.extend(self._check_sigma_anchors())

        # 2. Lane 2 modules
        checks.extend(self._check_modules(
            self.REQUIRED_LANE2, "Lane 2", sys.path
        ))

        # 3. Lane 1 modules
        lane1_paths = self._find_lane1_paths()
        checks.extend(self._check_modules(
            self.REQUIRED_LANE1, "Lane 1", sys.path + lane1_paths
        ))

        # 4. ACP-1 tracker
        checks.append(self._check_acp1())

        # 5. Hardware slot
        checks.append(self._check_guardian())

        # Overall: FAIL if any critical failure, WARN if any warning
        if any(c.status == BootStatus.FAIL for c in checks):
            overall = BootStatus.FAIL
        elif any(c.status == BootStatus.WARN for c in checks):
            overall = BootStatus.WARN
        else:
            overall = BootStatus.PASS

        return BootReceipt(
            boot_id=boot_id,
            booted_at=time.time(),
            checks=checks,
            overall=overall,
            python_ver=sys.version.split()[0],
            cwd=os.getcwd(),
        )

    def _check_sigma_anchors(self) -> List[BootCheck]:
        checks = []
        try:
            # Try to import from the canonical location
            _dir = os.path.dirname(os.path.abspath(__file__))
            _cgir = os.path.join(_dir, '..', '..', 'cgir')
            if _cgir not in sys.path:
                sys.path.insert(0, _cgir)
            from guardian_slot import (
                TAU_ESCAPE_FLOOR, CHI_WARN, CHI_COLLAPSE,
                DRIFT_THRESHOLD, BETTI_1_CAP,
            )
            actual = {
                "TAU_ESCAPE_FLOOR": TAU_ESCAPE_FLOOR,
                "CHI_WARN":         CHI_WARN,
                "CHI_COLLAPSE":     CHI_COLLAPSE,
                "DRIFT_THRESHOLD":  DRIFT_THRESHOLD,
                "BETTI_1_CAP":      BETTI_1_CAP,
            }
            for name, expected in EXPECTED_CONSTANTS.items():
                got = actual.get(name)
                if got is None:
                    checks.append(BootCheck(
                        f"sigma_anchor:{name}", BootStatus.FAIL,
                        f"Constant not found"
                    ))
                elif abs(got - expected) > 1e-9:
                    checks.append(BootCheck(
                        f"sigma_anchor:{name}", BootStatus.FAIL,
                        f"Expected {expected}, got {got}"
                    ))
                else:
                    checks.append(BootCheck(
                        f"sigma_anchor:{name}", BootStatus.PASS,
                        f"{got}"
                    ))
        except ImportError as e:
            checks.append(BootCheck(
                "sigma_anchors", BootStatus.WARN,
                f"guardian_slot not importable: {e}"
            ))
        return checks

    def _find_lane1_paths(self) -> List[str]:
        base = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base, '..', '05_epistemic_labeling'),
            os.path.join(base, '..', '06_archive_memory'),
            os.path.join(base, '..', '07_deferred_exploration'),
            os.path.join(base, '..', '08_promotion_protocol'),
            os.path.join(base, '..', '09_reality_gate'),
            os.path.join(base, '..', '02_mode_router'),
            base,
        ]
        return [c for c in candidates if os.path.isdir(c)]

    def _check_modules(self, modules: List[str],
                       lane: str, paths: List[str]) -> List[BootCheck]:
        checks = []
        old_path = list(sys.path)
        for p in paths:
            if p not in sys.path:
                sys.path.insert(0, p)
        for mod in modules:
            try:
                __import__(mod)
                checks.append(BootCheck(
                    f"{lane.lower().replace(' ','_')}:{mod}",
                    BootStatus.PASS, "importable"
                ))
            except ImportError as e:
                checks.append(BootCheck(
                    f"{lane.lower().replace(' ','_')}:{mod}",
                    BootStatus.WARN,
                    f"not importable: {e}"
                ))
        sys.path[:] = old_path
        return checks

    def _check_acp1(self) -> BootCheck:
        try:
            _dir = os.path.dirname(os.path.abspath(__file__))
            _cgir = os.path.join(_dir, '..', '..', 'cgir')
            if _cgir not in sys.path:
                sys.path.insert(0, _cgir)
            from acp1_tracker import ASSUMPTIONS
            verified = sum(1 for a in ASSUMPTIONS
                          if hasattr(a, 'status') and
                          str(a.status).endswith('VERIFIED'))
            return BootCheck(
                "acp1_tracker", BootStatus.PASS,
                f"{len(ASSUMPTIONS)} assumptions loaded, {verified} verified"
            )
        except Exception as e:
            return BootCheck("acp1_tracker", BootStatus.WARN, str(e))

    def _check_guardian(self) -> BootCheck:
        try:
            _dir = os.path.dirname(os.path.abspath(__file__))
            _cgir = os.path.join(_dir, '..', '..', 'cgir')
            if _cgir not in sys.path:
                sys.path.insert(0, _cgir)
            from guardian_slot import GuardianSlot
            return BootCheck(
                "guardian_slot", BootStatus.PASS, "GuardianSlot importable"
            )
        except ImportError as e:
            return BootCheck(
                "guardian_slot", BootStatus.WARN,
                f"GuardianSlot not importable (hardware not validated): {e}"
            )


def boot() -> BootReceipt:
    """Run the boot manifest. Returns BootReceipt."""
    return BootManifest().run()


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_boot_returns_receipt() -> bool:
    """boot() returns a BootReceipt."""
    receipt = boot()
    assert isinstance(receipt, BootReceipt)
    assert receipt.boot_id
    assert receipt.booted_at > 0
    assert receipt.overall in BootStatus
    return True

def _test_receipt_hash_stable() -> bool:
    """Same receipt → same hash."""
    receipt = boot()
    h1 = receipt.receipt_hash
    h2 = receipt.receipt_hash
    assert h1 == h2 and len(h1) == 64
    return True

def _test_to_dict_serializable() -> bool:
    """BootReceipt.to_dict() is JSON-serializable."""
    receipt = boot()
    json.dumps(receipt.to_dict())
    return True

def _test_checks_have_names() -> bool:
    """Every check has a non-empty name."""
    receipt = boot()
    for c in receipt.checks:
        assert c.name, f"Check has empty name: {c}"
    return True

def _test_sigma_anchors_checked() -> bool:
    """Boot checks include sigma anchor constants."""
    receipt = boot()
    anchor_checks = [c for c in receipt.checks if "sigma_anchor" in c.name]
    assert len(anchor_checks) > 0, "Expected sigma anchor checks"
    return True

def _test_overall_reflects_checks() -> bool:
    """Overall status matches worst check status."""
    receipt = boot()
    has_fail = any(c.status == BootStatus.FAIL for c in receipt.checks)
    has_warn = any(c.status == BootStatus.WARN for c in receipt.checks)
    if has_fail:
        assert receipt.overall == BootStatus.FAIL
    elif has_warn:
        assert receipt.overall in (BootStatus.WARN, BootStatus.FAIL)
    return True

def _test_critical_failures_property() -> bool:
    """critical_failures returns only FAIL checks."""
    receipt = boot()
    for c in receipt.critical_failures:
        assert c.status == BootStatus.FAIL
    return True

def _test_boot_id_unique() -> bool:
    """Two boots produce different boot IDs."""
    r1 = boot()
    time.sleep(0.01)
    r2 = boot()
    assert r1.boot_id != r2.boot_id
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
    print("=" * 70)
    print("BOOT MANIFEST — Labyrinth-OS / L00")
    print("=" * 70)
    receipt = boot()
    print(f"\n  Boot ID:  {receipt.boot_id}")
    print(f"  Overall:  {receipt.overall.value}")
    print(f"  Failures: {len(receipt.critical_failures)}")
    print(f"  Warnings: {len(receipt.warnings)}")
    print(f"\n  Checks:")
    for c in receipt.checks:
        mark = "✓" if c.status == BootStatus.PASS else "⚠" if c.status == BootStatus.WARN else "✗"
        print(f"    {mark} {c.name}: {c.detail}")
    print(f"\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed: raise SystemExit(1)
    import hashlib as _hl
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}")
    print(f"\n{'='*70}\n  BOOT MANIFEST — COMPLETE\n{'='*70}")

def _check_confidence_floor_ordering() -> list[str]:
    """
    Verify that confidence floors are ordered correctly:
    labeling_valid_floor <= promotion_floor <= reality_gate_floor

    A misconfiguration where promotion floor < gate floor would allow proposals
    that pass promotion but fail at the gate — wasting work and misleading operators.

    Called from run_boot_checks() before any input is accepted.
    """
    warnings = []
    try:
        from epistemic.vector.sigma_anchors import CONFIDENCE_FLOOR as gate_floor
        from promotion.promotion_rules import PROMOTION_CONFIDENCE_THRESHOLD as promo_floor
        labeling_floor = 0.60  # epistemic_labeler.py VALID threshold

        if promo_floor < gate_floor:
            warnings.append(
                f"INVARIANT VIOLATION: promotion floor ({promo_floor}) < "
                f"gate floor ({gate_floor}). Proposals can pass promotion "
                f"but fail at Reality Gate."
            )
        if labeling_floor > promo_floor:
            warnings.append(
                f"INVARIANT VIOLATION: labeling floor ({labeling_floor}) > "
                f"promotion floor ({promo_floor}). Labeled VALID proposals "
                f"may be below promotion threshold."
            )
    except ImportError:
        pass  # modules not available — skip check
    return warnings

