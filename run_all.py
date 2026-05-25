"""
run_all.py — Sentinel-Core test suite
"""
from __future__ import annotations
import importlib
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Add all subpackages to path so imports work
_SUBPACKAGES = [
    "cgir", "epistemic", "execution", "gate", "governance",
    "ledger", "memory", "observability", "proofs", "replay",
    "system", "tests"
]
for _pkg in _SUBPACKAGES:
    _pkg_path = os.path.join(_HERE, _pkg)
    if os.path.isdir(_pkg_path) and _pkg_path not in sys.path:
        sys.path.insert(0, _pkg_path)

SUITES = [
    (1, "sigma_anchors",      "Z3-proven Sigma Anchor constants (A021)"),
    (2, "pipeline_wire",      "Constitutional pipeline ordering (I1-I19)"),
    (2, "epistemic_types",    "IdeaNode, EpistemicLabel, InputMode types"),
    (2, "epistemic_labeler",  "Epistemic labeling — SPECULATIVE/DEFERRED/TRUTH"),
    (3, "archive_memory",     "Append-only epistemic archive"),
    (3, "reality_gate",       "Single crossing point Lane 1 → Lane 2"),
    (4, "cgir_types",         "CGIR typed execution graph"),
    (4, "cgir_core",          "CGIR graph construction and validation"),
    (4, "cgir_validator",     "CGIR constraint validation"),
    (4, "cgir_determinism",   "Deterministic hash for exact replay"),
    (5, "cgir_gate",          "Sigma Anchor gate — ALLOW/BLOCK"),
    (5, "guardian_slot",      "Final EXECUTE/BLOCK/KILL decision"),
    (6, "receipt",            "Typed immutable receipts"),
    (6, "hashchain",          "WORM SHA-256 hash chain (thread-safe)"),
    (6, "cgir_ledger",        "Session ledger with AEGIS phases"),
    (7, "replay_validator",   "Exact structural replay — EXACT only"),
    (8, "z3_promotion_proof", "Z3 promotion rule proofs PR1-PR8"),
    (8, "z3_predicate_proof", "Z3 predicate invariant proofs PP1-PP9"),
    (8, "test_invariants_i12_i13_i16_i19", "Invariant tests: I12/I13/I16/I19"),
    # Sovereignty + formal verification
    (9, "z3_sovereignty_spec",     "Z3 sovereignty specification proofs (22)"),
    # Constitutional layers
    (3, "gate_function",           "Pre-CGIR gate function"),
    (3, "gate_binding",            "Gate binding layer"),
    (3, "gate_proof",              "Gate formal proof"),
    (3, "gate_rejection",          "Gate rejection types"),
    (4, "acbf_vm",                 "ACBF ITV reference VM"),
    (4, "aegis_cesk",              "AEGIS CESK abstract machine"),
    (4, "cgir_signal_algebra",     "CGIR signal algebra (29)"),
    (4, "cgir_guardian_bridge",    "CGIR guardian bridge (12)"),
    # Watchers + council
    (5, "watcher_a",               "Watcher A — epistemic signal monitor"),
    (5, "watcher_b",               "Watcher B — epistemic signal monitor"),
    (5, "council_resolver",        "Council resolver — watcher majority vote"),
    # Healing + observability
    (5, "circuit_breaker",         "EWMA circuit breaker + evolution engine"),
    (5, "metrics",                 "Metrics collector — stage telemetry"),
    # Promotion layer
    (6, "promotion_rules",         "Promotion rules — Z3-proven conditions"),
    (6, "rollback_protocol",       "Rollback protocol"),
    (6, "audit_trail",             "Audit trail — promotion decisions"),
    # Labeling layer
    (6, "label_schema",            "Epistemic label schema"),
    (6, "label_validator",         "Epistemic label validator"),
    # Test harness
    (7, "test_harness",            "Test harness — promotion testing"),
    (7, "threat_model",            "TM-001 threat model — 11 attack classes"),
    # Integration + adversarial tests
    (9, "test_sigma_boundary_sweep","Sigma anchor boundary sweep (23)"),
    (9, "test_determinism",        "Determinism guarantee (19)"),
    (9, "test_full_pipeline",      "Full pipeline integration (28)"),
    (9, "test_forced_failure",     "Forced failure adversarial (12)"),
    (9, "test_property_based",     "Property-based tests (10)"),
    (9, "promotion_tests",         "Promotion tests (44)"),
    (9, "test_epistemic_boundary", "Epistemic boundary tests"),
    (9, "test_labeling_to_reality_gate", "L05→L09 integration"),    # Archive layer
    (4, "memory_store",              "Epistemic memory store"),
    (4, "pattern_catalog",           "Pattern catalog"),
    (4, "recall_protocol",           "Recall protocol"),
    (4, "chunk_store",               "Compressed archive + hot index"),
    (4, "confidence_record",         "Label confidence accuracy tracker"),
    # Labeling layer (extended)
    (5, "confidence_meter",          "Confidence measurement"),
    (5, "promotion_protocol",        "Promotion protocol (Lane 1 L08)"),
    # Observability layer
    (5, "drift_detector",            "Drift detection"),
    (5, "anomaly_log",               "Anomaly log"),
    (5, "feedback_loop",             "Feedback loop"),
    # Extended test coverage
    (8, "labeling_tests",            "Labeling tests (40)"),
    (8, "observability_tests",       "Observability tests (28)"),
    (9, "test_watcher_council",      "Watcher council tests (30)"),
    (9, "test_domain_adapter_contracts","Domain adapter contracts (21)"),
    (9, "test_guardian_bridge_dedicated","Guardian bridge dedicated (10)"),
    (9, "test_rust_python_differential","Rust/Python differential parity (7)"),
    (9, "test_ci_gaps",              "CI gap coverage (18)"),
    (9, "test_observability_to_archive","Observability→archive integration (5)"),    # Boot + learning
    (2, "boot_manifest",             "Boot manifest (8)"),
    (2, "boot_preflight",            "Boot preflight checks (8)"),
    (2, "mode_router",               "Mode router L02 (10)"),
    (3, "continuous_learning_loop",  "Continuous learning loop (12)"),
    # Final test coverage
    (9, "test_labeling",             "Labeling tests epistemic (7)"),
    (9, "test_observability",        "Observability tests epistemic (7)"),    (9, "test_rust_python_parity",   "Rust/Python parity integration (7)"),
    (9, "test_feedback_loop_e2e",    "Feedback loop E2E (7)"),
    (9, "test_watcher_council_bounds","Watcher council bounds (5)"),
    (9, "test_promotion",            "Promotion epistemic tests (7)"),
    (9, "test_archive",              "Archive epistemic tests (7)"),
    # ── Synced from Portable ────────────────────────────────────────────────
    (20, "system_snapshot",  "System state capture — immutable boot points, hash-verified"),
    (20, "sandbox_runner",   "Sandbox testing of proposals before live deployment"),
    (20, "user_feedback",    "User-driven evolution — plain-language feedback to proposals"),
    (20, "proposal_review",  "Governance protocol — mandatory hidden agenda disclosure"),

    # ── Synced from other-chat Core v7 ─────────────────────────────────────
    (20, "enforcement_mode",  "HARD/SOFT enforcement — single flag, same gate, different response"),
    (20, "output_labeler",    "Output labeller — CLEAR/CAUTION/HALLUCINATION for SOFT mode"),

]

def run() -> None:
    print("=" * 60)
    print("SENTINEL-CORE — TEST SUITE")
    print("=" * 60)

    total_p = total_f = 0
    failures = []
    t0 = time.perf_counter()

    for tier, module, desc in SUITES:
        try:
            mod = importlib.import_module(module)
            if not hasattr(mod, "run_tests"):
                print(f"  SKIP: {module} (no run_tests)")
                continue
            p, f, results = mod.run_tests()
            total_p += p
            total_f += f
            status = "✓" if f == 0 else "✗"
            print(f"  {status} {module:<28} {p}/{p+f}")
            if f > 0:
                failures.append(module)
                for name, st, err in results:
                    if st == "FAIL":
                        print(f"      FAIL: {name}: {(err or '')[:80]}")
        except Exception as e:
            total_f += 1
            failures.append(module)
            print(f"  ✗ {module:<28} ERROR: {str(e)[:60]}")

    elapsed = time.perf_counter() - t0
    print()
    print(f"  TOTAL: {total_p} passed / {total_f} failed  ({elapsed:.1f}s)")
    print()

    # Self-test the runtime itself
    try:
        from sentinel_core import _self_test
        _self_test()
        print("  ✓ sentinel_core — runtime self-test")
    except Exception as e:
        total_f += 1
        print(f"  ✗ sentinel_core — runtime self-test FAILED: {e}")

    print()
    if total_f == 0:
        print("  ✓ ALL TESTS PASS")
    else:
        print(f"  ✗ FAILURES in: {failures}")
    print("=" * 60)
    return total_f

if __name__ == "__main__":
    import sys
    result = run()
    if result and result != 0:
        sys.exit(1)
