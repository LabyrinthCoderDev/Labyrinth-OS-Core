## v1.6 — May 2026 (enforcement_mode + output_labeler)

### Synced from other-chat Core v7 + Portable v15

**enforcement_mode.py** — HARD/SOFT enforcement flag.
  Single parameter controlling how the gate responds to a failed check.
  HARD: EXECUTE/BLOCK/KILL — for robots and physical systems.
  SOFT: EXECUTE + honest epistemic labels — for agents and apps.
  Same gate. Same Z3-proven constants. Same WORM ledger. One flag changes
  the response to a failure. 7 tests.

**output_labeler.py** — Honest labelling of AI responses in SOFT mode.
  CLEAR / CAUTION / LOW_CONFIDENCE / LIKELY_HALLUCINATION / HIGH_DRIFT / UNRELIABLE.
  Gate still runs. Decisions still logged. Response always shown.
  Label gives the user honest information to make their own decision. 10 tests.

**sigma_anchors.py** — Added TAU_KILL_FLOOR=0.60 and CHI_KILL=0.50.
  These constants existed implicitly. Now explicit and importable.

### Tests
  v1.5: 1,085 tests
  v1.6: 1,102 tests (+17)
  Failures: 0

---

## v1.5 — May 2026 (Portable sync)

### Synced from Portable v14

**system_snapshot.py** — Full constitutional enforcement state capture.
  Immutable once saved. Hash-verified. Named boot points:
  'baseline' (first boot, immutable forever), 'pre_update_<ts>' (before
  every approved change), 'sandbox_<ts>' (before sandbox test run),
  user-named (manual). 10 tests.

**sandbox_runner.py** — Safe proposal testing before live deployment.
  When an approved proposal runs, current state is snapshotted first,
  changes applied to a sandbox copy, N turns run with BUILTIN engine,
  degradation monitored vs baseline. Fail = auto-rollback, owner report.
  Pass = owner confirms live deployment. Owner always sees sandbox result
  before anything goes live. 5 tests.

**user_feedback.py** — User-driven evolution entry point.
  User provides plain-language feedback ('the system keeps blocking my
  coding questions'). System searches session history, measures actual
  block rate for that category, computes bounded adjustment, generates
  full ProposalPacket with mandatory hidden agenda disclosure. Same
  approval flow as any other proposal. Gate still runs. 8 tests.

**proposal_review.py** — Governance protocol with mandatory hidden agenda
  disclosure. ProposalPacket, HiddenAgendaSection, ReviewerFinding,
  ProposalQueue. No change applied without explicit owner approval.
  Empty agenda auto-flagged. 12 tests.

### Compatibility patches applied
  - DegradeState.NOMINAL → HEALTHY, DegradeState.ANOMALY → DEGRADE
    (Core uses HEALTHY/WARNING/DEGRADE; Portable uses NOMINAL/WARNING/ANOMALY)
  - 'from core.X import' → 'from X import' (Core is flat, not packaged)
  - 'from healing.healing_system import' → 'from circuit_breaker import'

### Tests
  v1.4: 1,050 tests
  v1.5: 1,085 tests (+35)
  Failures: 0

---

## v1.4 — May 2026 (complete sweep — production grade)

### Added — final module set (33 tests)

All modules added after exhaustive sweep of full system.
Every module that passes in Core's flat structure with no A010 dependency.

Integration tests: test_rust_python_parity (7), test_feedback_loop_e2e (7),
  test_watcher_council_bounds (5), test_promotion (7), test_archive (7)
Boot layer: boot_manifest (8), boot_preflight (8), mode_router (10)
Learning: continuous_learning_loop (12)
Labeling: test_labeling (7), test_observability (7)
Observability: drift_detector (8), anomaly_log (8), feedback_loop (8)
Archive: memory_store (6), pattern_catalog (9), recall_protocol, chunk_store, confidence_record
Watcher council: test_watcher_council (30), test_domain_adapter_contracts (21),
  test_guardian_bridge_dedicated (10), test_rust_python_differential (7), test_ci_gaps (18)
Labeling extended: labeling_tests (40), confidence_meter (6), promotion_protocol (10)
Observability extended: observability_tests (28), test_observability_to_archive (5)

### Excluded (A010 / hardware gated)
  tau_baseline_generator — needs live logprob data
  logprob_bridge_adapter — needs live LLM
  ignition/test_ignition_enforcement — needs full session runtime

### Tests
  v1.3: 723 tests
  v1.4: 1,050 tests (+327)
  Failures: 0
  Python files: 75 (+)

---

## v1.3 — May 2026 (comprehensive expansion)

### Added — 29 new modules from full system

All pass cleanly in Core's flat structure. Zero new dependencies outside Core.

Constitutional layers:
  gate_function, gate_binding, gate_proof, gate_rejection, acbf_vm
  aegis_cesk, cgir_signal_algebra, cgir_guardian_bridge

Watcher + council:
  watcher_a, watcher_b, council_resolver

Healing + observability:
  circuit_breaker (EWMA + EvolutionEngine), metrics

Promotion layer:
  promotion_rules (upgraded), rollback_protocol, audit_trail

Labeling layer:
  label_schema, label_validator

Integration + adversarial tests:
  test_sigma_boundary_sweep (23), test_determinism (19),
  test_full_pipeline (28), test_forced_failure (12),
  test_property_based (10), promotion_tests (44),
  test_epistemic_boundary, test_labeling_to_reality_gate

Formal verification:
  z3_sovereignty_spec (22 proofs)

Infrastructure:
  test_harness, threat_model (TM-001, 11 attack classes)

### Fixed
  sovereignty_receipt.json created with correct schema fields

### Tests
  v1.2: 317 tests
  v1.3: 723 tests (+406)
  Failures: 0
  Files: 55

---

## v1.2 — May 2026 (deep audit)

### Bugs fixed
- betti_1 not passed to GuardianSlot — betti breaches now correctly KILL not EXECUTE
- sensor_snapshot incomplete on partial input — now always shows all 5 channels with defaults
- Self-test expectations corrected — chi_collapse and betti_breach are KILL not BLOCK (by design)

### Stale refs cleaned
- README, WHAT_THIS_IS, SNAPSHOT updated: Robot=380 tests, Core=317, Albedo removed

### Tests
- v1.1: 317 tests
- v1.2: 317 tests (same count — bug fixes, no new modules)
- Failures: 0

---

# Sentinel-Core — Changelog

---

## v1.1 — May 2026

### New modules
- `z3_promotion_proof.py` — 8 Z3 proofs (PR1-PR8) for promotion rule consistency
- `z3_predicate_proof.py` — 9 Z3 proofs (PP1-PP9) for predicate invariants
- `promotion_rules.py` — promotion rule definitions (dependency of Z3 proofs)
- `test_invariants_i12_i13_i16_i19.py` — explicit tests for I12/I13/I16/I19
- `SNAPSHOT.md`, `CHANGELOG.md` — project state documentation

### Fixes
- Empty content in `sentinel_core.process()` no longer crashes — uses `[no content]` placeholder
- `reality_gate.py` classification warning silenced — EpistemicClassifier not needed in Core
- Block reason improved: low-confidence blocks now report `CONFIDENCE_BELOW_FLOOR` not `WRONG_LABEL`
- `INVARIANTS.md` path reference in invariant tests fixed for Core's flat structure
- `I13` test adapted: checks `cgir_ledger.py` (Core's observability layer) not full system metrics module

### Test counts
- v1.0: 292 tests
- v1.1: 317 tests (+25)
- Failures: 0

---

## v1.0 — May 2026 (initial)

### 16 core modules
sigma_anchors, pipeline_wire, epistemic_types, epistemic_labeler, archive_memory,
reality_gate, cgir_types, cgir_core, cgir_validator, cgir_gate, guardian_slot,
receipt, hashchain, cgir_determinism, cgir_ledger, replay_validator

### Single-file runtime
`sentinel_core.py` — import SentinelCore, call process(), call replay().
Self-contained. No stubs. No PARTIAL gaps. No mocks.

### 292 tests, 0 failures
