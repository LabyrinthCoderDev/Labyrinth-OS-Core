# Labyrinth OS — Build Journal
**@LabyrinthCoder** | Started: May 2026

---

## How This Journal Works

Updated every session. Delivered with every ZIP + TXT. Never stale.
Completed items removed. New items added immediately.

**File delivery rule:** ZIP + TXT + JOURNAL.md together, every time.
**Tex rule:** .tex files generated on request or when a system reaches GitHub-ready status.

---

## The Five Systems

| System | What It Is | Tests | Version | .tex |
|--------|-----------|-------|---------|------|
| Full | Full research system | 1,556 | v1 (not actively built) | exists (check if current) |
| Mini | Original robot + Rust crates | — | v1 (reference) | exists |
| Robot | Cleaned Mini | 660 | v4 | ✓ Labyrinth-OS-Robot.tex |
| Core | Deployable kernel | 1,050 | v5 | ✓ Labyrinth-OS-Core.tex |
| Portable | Consumer mobile app | 172 | v11 | ✓ Labyrinth-OS-Portable.tex |

**Inheritance:** Full → Mini → Robot → Core → Portable

---

## Build 1 — Labyrinth OS Portable

**Current version:** v11
**File:** Labyrinth-OS-Portable-v6.zip / .txt
**Tests:** 172 passing / 0 failing
**Status:** Active development
**.tex:** Labyrinth-OS-Portable.tex ✓

### Done
- [x] Constitutional gate — Rust Blake3 + Python fallback + parity tests
- [x] WORM ledger — SHA-256, 0o600 permissions, tamper-evident
- [x] Epistemic labeller — no KILL, honest labels only
- [x] WAL SQLite memory — FTS5, checkpoints, importances
- [x] Model registry — clone / snapshot / export / import
- [x] Streaming backends — Ollama, llama.cpp, Claude, OpenAI, BUILTIN
- [x] Built-in reasoning engine — works with no external model
- [x] Self-healing — circuit breaker + EWMA degradation + evolution
- [x] Governance protocol — proposals queue, mandatory hidden agenda disclosure
- [x] Z3 formal proofs — promotion rules PR1-PR8 + predicate invariants PP1-PP9
- [x] Tool feedback loop — tool results re-enter LLM for follow-up
- [x] Tools — file / shell / web / memory, all gated individually
- [x] DuckDuckGo search hardened — retry, dual endpoint, rate limit, graceful error
- [x] GGUF model downloader — resumable, verified, cancellable
- [x] Multi-agent — orchestrator routes to specialists, MAX_HOPS=4
- [x] CLI — /create /proposals /approve /reject /chain /memory /help
- [x] Flutter: setup, model select, chat, settings, model builder wizard
- [x] Flutter: memory browser, proposals screen, ledger viewer
- [x] Flutter: per-model tool permissions display
- [x] App icon — all 5 Android mipmap resolutions
- [x] Android — AgentService.kt, wake lock, crash-safe boot flag
- [x] GitHub Actions CI pipeline
- [x] WHAT_THIS_IS.md, README, CHANGELOG, LICENSE, .gitignore
- [x] server.py smoke tests (6 tests)
- [x] proposal_review.py USAGE section
- [x] gate_bridge.py cross-reference to epistemic_labeler.py
- [x] .tex academic paper written

### Next
- [ ] betti_1 real computation — always 0.0 (needs vector sensors from Full system)
- [ ] Multi-agent: shared memory concurrent write conflict resolution
- [ ] iOS / desktop packaging (v1.4)
- [ ] Play Store submission — owner decides timing
- [ ] proposals/submit route in server.py (currently only decide + pending)

### Design decisions (not bugs)
- No KILL in portable — epistemic labels instead (consumer product)
- betti_1 = 0.0 — documented placeholder
- Blake3 in Rust, SHA-256 in Python fallback — decisions identical
- Single agent per data directory — by design
- Snapshots immutable — audit trail by design

---

## Build 2 — Labyrinth OS Core

**Current version:** v5
**File:** Labyrinth-OS-Core-v6.zip / .txt
**Tests:** 1,050 passing / 0 failing
**Status:** Stable, GitHub-ready
**.tex:** Labyrinth-OS-Core.tex ✓

### Done
- [x] 16-module kernel expanded to 79 Python files
- [x] Full constitutional pipeline
- [x] Z3 proofs: sovereignty (22), promotion PR1-PR8 (8), predicate PP1-PP9 (9)
- [x] Watcher/council: watcher_a, watcher_b, council_resolver
- [x] Observability: circuit_breaker, metrics, drift_detector, anomaly_log, feedback_loop
- [x] Archive: memory_store, pattern_catalog, recall_protocol, chunk_store, confidence_record
- [x] Boot: boot_manifest, boot_preflight, mode_router, continuous_learning_loop
- [x] Integration/adversarial: boundary sweep, determinism, full pipeline, forced failure,
      property-based, watcher council, domain adapters, guardian bridge, Rust/Python differential
- [x] Threat model TM-001 (11 attack classes)
- [x] .hypothesis/ excluded from distribution
- [x] Docs: SNAPSHOT, CHANGELOG, WHAT_THIS_IS, VERSION
- [x] External review — "production-ready, no critical gaps"
- [x] Review fixes applied
- [x] .tex academic paper written

### Next
- [ ] Sync epistemic labeller (no-KILL design) from Portable back to Core
- [ ] Sync governance protocol from Portable back to Core

---

## Build 3 — Labyrinth OS Robot

**Current version:** v4
**File:** Labyrinth-OS-Robot-v4.zip / .txt
**Tests:** 660 passing / 0 failing
**Status:** GitHub-ready
**.tex:** Labyrinth-OS-Robot.tex ✓

### Done
- [x] Cleaned from Mini — 12 stale docs removed
- [x] Full rename: Albedo → Robot (zero albedo refs in .py files)
- [x] Rust crates: labyrinth-gate, labyrinth-gate-pyo3, labyrinth-robot-adapter, labyrinth-sigma-anchors
- [x] run_all.py, .gitignore, LICENSE
- [x] Z3 proofs: z3_promotion_proof, z3_predicate_proof, z3_robot_threshold_proof
- [x] physics_sentinel (Layer 0 pre-gate density invariant)
- [x] Private names cleaned (academic citation form)
- [x] External review — "production-ready, no critical gaps"
- [x] Core v5 expansion: watcher/council, observability, boot, archive, labeling, integration tests
  - watcher_a, watcher_b, council_resolver (42 tests)
  - metrics, drift_detector, anomaly_log, feedback_loop (34 tests)
  - boot_manifest, boot_preflight, mode_router, continuous_learning_loop (38 tests)
  - memory_store, pattern_catalog, recall_protocol, chunk_store, confidence_record (43 tests)
  - label_schema, label_validator, confidence_meter (18 tests)
  - test_determinism, test_property_based, test_forced_failure, test_sigma_boundary_sweep,
    test_watcher_council (94 tests)
- [x] worm_ledger compatibility: phase field, verify_chain alias, session_id attribute
- [x] replay_validator_core.py as separate from robot's replay_validator
- [x] .tex academic paper written

### Next
- [ ] deferred_node.py (P3-01 roadmap)
- [ ] threat_model extension (P3-04)
- [ ] Robot .tex needs table count update (currently estimates in test table)

---

## Build 4 — Labyrinth OS Mini

**Version:** v1 | **Status:** Reference only

Original robot + 4 Rust crates. 52 files. .tex document exists.
Not actively built. Rust crate architecture is reference for Portable's gate.

---

## Build 5 — Labyrinth OS Full

**Version:** v1 | **File:** Labyrinth-OS-v2.zip / .txt | **Tests:** 1,556

**Status:** Research system — not actively built

### Next (when resumed)
- [ ] Dialogue logs polish — Q&A reads as clean technical dialogue, no filler words
- [ ] WHAT_THIS_IS.md — update to show all 5 systems
- [ ] Absorb from Portable: epistemic labeller, governance protocol
- [ ] Absorb from Core v5: expanded test suite modules
- [ ] GAP 1, 6, 7, 13 — blocked on external hardware/data dependencies

---

## Cross-Build Notes

**Portable → Core (should flow back):**
- Epistemic labeller (no-KILL design)
- Governance protocol with mandatory hidden agenda disclosure

**Blake3 / SHA-256 split (by design):**
- Rust gate: Blake3 | Python fallback: SHA-256 (not in stdlib)
- Gate decisions are identical — only hash format differs

**worm_ledger compatibility (Robot):**
- LedgerEntry.phase added (default "") for Core integration test compatibility
- verify_chain() added as alias for verify()
- session_id attribute added to CGIRLedger

---

## Session Log

| Session | Build | Version | What was done |
|---------|-------|---------|---------------|
| 1 | Portable | v1 | Core Python — gate, memory, registry, WORM ledger |
| 2 | Portable | v2 | Rust gate, Blake3, streaming backends, healing |
| 3 | Portable | v3 | Flutter app, Android build, GitHub Actions |
| 4 | Portable | v4 | Epistemic labeller, built-in engine, KILL removed |
| 5 | Portable | v5 | Privacy scrub, WHAT_THIS_IS.md |
| 6 | Portable | v6 | Tool feedback loop, model downloader wired |
| 7 | Portable | v7 | AgentService.kt, wake lock, crash-safe boot |
| 8 | Portable | v8 | Governance, Z3 proofs, tool feedback complete |
| 9 | Portable | v9 | Governance wired to healing, model builder, app icon, screens |
| 10 | Portable | v10 | Multi-agent, CLI commands, server endpoints, journal created |
| 11 | Portable | v11 | Deep audit: DuckDuckGo hardened, server tests, USAGE sections, 172 tests |
| 11 | Core | v5 | Exhaustive sweep: 317 → 1,050 tests, bugs fixed, reviewed |
| 11 | Robot | v3 | Rust crates merged, full rename, reviewed |
| 12 | Robot | v4 | Core v5 expansion: 380 → 660 tests, watcher/council/observability/boot |
| 12 | All | — | .tex files written: Portable, Core, Robot |

---

## .Tex Tracker

| Build | File | Status |
|-------|------|--------|
| Full | (from earlier session) | Check if current |
| Mini | (from earlier session) | Current |
| Robot | Labyrinth-OS-Robot.tex | ✓ Written this session |
| Core | Labyrinth-OS-Core.tex | ✓ Written this session |
| Portable | Labyrinth-OS-Portable.tex | ✓ Written this session |

**Format:** `\documentclass[12pt,a4paper]{article}`, title page, abstract, ToC.
**Header:** `\rhead{<System>}` `\lhead{@LabyrinthCoder}`
**Title page:** name, @LabyrinthCoder, Anonymous independent researcher, May 2026, prototype disclaimer.
**Compile:** `pdflatex <file>.tex` (requires texlive-full or equivalent)

---

*@LabyrinthCoder — updated every session*
