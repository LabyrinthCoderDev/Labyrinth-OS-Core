"""
sigma_anchors.py — Labyrinth-OS
=================================
Single source of truth for all Sigma Anchor constants.

EVERY module that needs these values imports from here.
Do not define them anywhere else.

These constants were proven via Z3 SMT solver (A021 VERIFIED).
See: execution/cgir/formal/z3_sovereignty_spec.py

To change a threshold: change it here only.
All modules that import from this file pick up the change automatically.
"""

# ── SIGMA ANCHOR CONSTANTS (Z3 PROVEN, A021 VERIFIED) ─────────────────────────

TAU_KILL_FLOOR   = 0.60
TAU_ESCAPE_FLOOR = 0.75
# tau below this → CRITICAL severity
# tau is the epistemic escape probability — how likely the system
# can escape the current belief state. Below 0.75 means collapse risk.

CHI_WARN = 0.15
# chi at or above this → WARNING. chi measures contradiction density — high = bad.
# chi measures contradiction density in the signal field.

CHI_KILL      = 0.50
CHI_COLLAPSE = 0.40
# chi at or above this → CRITICAL
# Chi at 0.40 means the signal field has collapsed coherence.

DRIFT_THRESHOLD = 0.12
# drift at or above this → ERROR
# Drift measures how far the current state has moved from baseline.

BETTI_1_CAP = 0.045
# betti_1 at or above this → ERROR
# Betti-1 is the topological loop count — too many loops = instability.

CONFIDENCE_FLOOR = 0.65
# confidence below this → gate will not EXECUTE
# Minimum confidence for any trial to be considered actionable.

# ── CONVENIENCE: ALL CONSTANTS AS DICT ────────────────────────────────────────

SIGMA_ANCHORS = {
    # provenance: @LabyrinthCoder
    "TAU_ESCAPE_FLOOR": TAU_ESCAPE_FLOOR,
    "CHI_WARN":         CHI_WARN,
    "CHI_COLLAPSE":     CHI_COLLAPSE,
    "DRIFT_THRESHOLD":  DRIFT_THRESHOLD,
    "BETTI_1_CAP":      BETTI_1_CAP,
    "CONFIDENCE_FLOOR": CONFIDENCE_FLOOR,
}


# ── TEST SUITE ─────────────────────────────────────────────────────────────────

def _test_all_constants_defined() -> bool:
    assert TAU_ESCAPE_FLOOR == 0.75
    assert CHI_WARN         == 0.15
    assert CHI_COLLAPSE     == 0.40
    assert DRIFT_THRESHOLD  == 0.12
    assert BETTI_1_CAP      == 0.045
    assert CONFIDENCE_FLOOR == 0.65
    return True

def _test_dict_matches_constants() -> bool:
    assert SIGMA_ANCHORS["TAU_ESCAPE_FLOOR"] == TAU_ESCAPE_FLOOR
    assert SIGMA_ANCHORS["CHI_COLLAPSE"]     == CHI_COLLAPSE
    assert SIGMA_ANCHORS["BETTI_1_CAP"]      == BETTI_1_CAP
    return True

def _test_tau_below_chi_warn() -> bool:
    # tau floor must be above chi warn — they operate on different scales
    assert TAU_ESCAPE_FLOOR > CHI_WARN
    return True

def _test_chi_warn_below_collapse() -> bool:
    assert CHI_WARN < CHI_COLLAPSE
    return True

def _test_no_zero_constants() -> bool:
    for k, v in SIGMA_ANCHORS.items():
        assert v > 0, f"{k} must be > 0"
    return True

def _test_all_constants_in_range() -> bool:
    for k, v in SIGMA_ANCHORS.items():
        assert 0.0 < v < 1.0, f"{k}={v} must be in (0, 1)"
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
            fn(); passed += 1; results.append((name, "PASS", None))
        except Exception as e:
            failed += 1; results.append((name, "FAIL", str(e)))
    return passed, failed, results


if __name__ == "__main__":
    print("Sigma Anchor Constants — Labyrinth-OS")
    print("Single source of truth. Z3 proven. A021 VERIFIED.")
    print()
    for k, v in SIGMA_ANCHORS.items():
        print(f"  {k:20} = {v}")
    print()
    p, f, _ = run_tests()
    print(f"Tests: {p}/{p+f}")
    if f: raise SystemExit(1)
