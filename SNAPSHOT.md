# Sentinel-Core — Snapshot
## Version 1.1 | May 2026

---

## Test Counts

| Layer | Tests | Failures |
|-------|-------|---------|
| Python | 1,050 | 0 |
| Rust | n/a | — |
| **Total** | **1,050** | **0** |

---

## Files

| File | Role | Tests |
|------|------|-------|
| `sentinel_core.py` | Main runtime | self-test |
| `sigma_anchors.py` | Z3-proven thresholds (A021) | 6 |
| `pipeline_wire.py` | Constitutional ordering | 17 |
| `epistemic_types.py` | Core types | 12 |
| `epistemic_labeler.py` | Labeling | 11 |
| `archive_memory.py` | Append-only archive | 10 |
| `reality_gate.py` | Single crossing point | 11 |
| `cgir_types.py` | Typed execution graph | 21 |
| `cgir_core.py` | Graph construction | 24 |
| `cgir_validator.py` | Constraint validation | 25 |
| `cgir_determinism.py` | Deterministic hashing | 18 |
| `cgir_gate.py` | Sigma Anchor gate | 21 |
| `guardian_slot.py` | Final EXECUTE/BLOCK/KILL | 28 |
| `receipt.py` | Typed immutable receipts | 25 |
| `hashchain.py` | WORM hash chain | 29 |
| `cgir_ledger.py` | Session ledger | 24 |
| `replay_validator.py` | Exact replay | 10 |
| `z3_promotion_proof.py` | Z3 promotion proofs PR1-PR8 | 8 |
| `z3_predicate_proof.py` | Z3 predicate proofs PP1-PP9 | 9 |
| `promotion_rules.py` | Promotion rule definitions | — |
| `test_invariants_i12_i13_i16_i19.py` | Invariant tests | 8 |
| `run_all.py` | Test suite | — |
| `sentinel_core.py` | Main runtime | — |
| `README.md` | Documentation | — |
| `WHAT_THIS_IS.md` | Identity document | — |
| `SNAPSHOT.md` | This file | — |
| `CHANGELOG.md` | Version history | — |

---

## What Is Proven

| Claim | Status | Evidence |
|-------|--------|---------|
| Sigma Anchor thresholds consistent | Z3-PROVEN | sigma_anchors.py (A021) |
| Promotion rules non-contradictory | Z3-PROVEN | z3_promotion_proof.py PR1-PR8 |
| Predicate invariants hold | Z3-PROVEN | z3_predicate_proof.py PP1-PP9 |
| Pipeline ordering enforced | TEST-VERIFIED | pipeline_wire.py (I1-I19) |
| Ledger tamper-evident | TEST-VERIFIED | hashchain.py |
| Replay exact | TEST-VERIFIED | replay_validator.py |
| Gate cannot be bypassed | TEST-VERIFIED | reality_gate.py + cgir_gate.py |
| Final decision typed | TEST-VERIFIED | guardian_slot.py |
| Archive append-only | TEST-VERIFIED | test_invariants I12 |
| Session isolation thread-safe | TEST-VERIFIED | test_invariants I19 |

---

## What This Is Not

- Not a language model or AI system
- Not the full Sentinel-Substrate (no healing, no ACP-1, no domain adapters)
- Not the robot deployment layer
- Not the portable consumer app

This is the minimal deployable constitutional enforcement kernel.
