<div align="center">

# Labyrinth-OS · Sentinel-Core

**Experimental runtime architecture for governed AI execution.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-1%2C102%20passing-brightgreen.svg)](RELEASE_CHECKLIST.md)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)]()
[![Status](https://img.shields.io/badge/status-experimental%20prototype-orange.svg)]()
[![Z3 Verified](https://img.shields.io/badge/Z3-formally%20verified-blueviolet.svg)]()
[![Author](https://img.shields.io/badge/%40LabyrinthCoder-X-black.svg)](https://x.com/LabyrinthCoder)

<br>

*Independent research prototype · not production-hardened · open to scrutiny*

</div>

---

## What This Repository Actually Is

Labyrinth-OS-Core is an experimental runtime architecture exploring how adaptive AI systems can maintain replayability, traceability, bounded execution, and structured memory over time.

It is a **runnable research prototype** intended for experimentation, architecture study, and systems design exploration.

**Three plain-English questions answered:**

**What is this?**
A minimal, runnable substrate that enforces a constitutional pipeline between an AI proposal and its execution — with every decision logged, hash-chained, and replayable.

**What problem is it trying to solve?**
Most AI systems optimize for outputs. This project asks: what if the *structure between the model and the world* could enforce accountability — regardless of what the model wants?

**What does it actually do today?**
It takes a proposal in, runs it through a mandatory gate, logs every decision to a tamper-evident chain, and can replay any session exactly.

---

## What This Project Is NOT

```
✗  AGI
✗  Autonomous military software
✗  Self-replicating malware
✗  An autonomous swarm platform
✗  A production AI safety solution
✗  A replacement for formal security review
✗  A verified truth engine
✗  Finished
```

This is an experimental architectural substrate for research and educational purposes.

---

## Why This Exists

Most AI systems optimize only for outputs.

This project explores whether adaptive systems can instead be designed around:

- **Replayability** — every session can be reconstructed exactly
- **Accountability** — every decision is logged before it executes
- **Bounded execution** — only gate-approved proposals reach the execution layer
- **Auditability** — the ledger is tamper-evident and verifiable
- **Memory continuity** — archive before evaluation, never lose state
- **Observable state transitions** — every stage is inspectable

The goal is to experiment with architectural patterns — not to claim solved intelligence or safety.

---

## How It Works — The Execution Flow

```
INPUT
  │
  ▼
LABEL ──────────── Is this SPECULATIVE, DEFERRED, or TRUTH?
  │
  ▼
ARCHIVE ─────────── Store it immutably before touching it
  │
  ▼
REALITY GATE ────── Single crossing point. No bypass path.
  │                 Requires: TRUTH label + no contradiction
  ▼
CGIR ────────────── Translate to typed intermediate representation
  │                 Canonical hash — deterministic across runs
  ▼
SIGMA GATE ─────── Five-channel threshold check
  │                τ · χ · drift · β₁ · confidence
  │                Z3-formally-proven thresholds (A021)
  ▼
GUARDIAN ────────── Final decision: EXECUTE · BLOCK · KILL
  │
  ▼
LEDGER ─────────── SHA-256 hash chain — append-only — tamper-evident
  │
  ▼
REPLAY ─────────── Structural verification — CLEAN · VIOLATED
  │
  ▼
OBSERVABILITY ───── Metrics, drift detection, audit trail
```

---

## Currently Implemented

These components are wired end-to-end, test-verified, and runnable today:

| Component | What it does | Verified by |
|-----------|-------------|-------------|
| Epistemic labeler | Labels proposals SPECULATIVE / DEFERRED / TRUTH | Tests |
| Archive memory | Immutable pre-evaluation storage | Tests |
| Reality Gate | Single mandatory Lane 1 → Lane 2 crossing | Tests — no bypass path exists |
| CGIR representation | Typed execution graph with canonical hash | Tests — deterministic |
| Sigma Anchor Gate | Five-channel threshold enforcement | Z3 SMT proof (A021) |
| Guardian Slot | Final typed EXECUTE / BLOCK / KILL | Tests |
| WORM Ledger | SHA-256 hash chain, append-only | Tests — chain breaks on tamper |
| Replay Validator | Structural session replay | Tests |
| Watcher Council | Two independent watchers, strictest wins | Tests |
| Observability | Metrics, drift detection, anomaly logging | Tests |
| Promotion Protocol | SPECULATIVE → TRUTH graduation rules | Tests + Z3 proofs |

---

## Long-Term Research Directions

These are aspirations — not currently implemented:

- Multi-agent constitutional coordination across distributed nodes
- Formal end-to-end safety verification (Z3 covers thresholds only)
- Adversarial hardening for hostile-operator scenarios
- PyPI-installable package with proper import hygiene
- Semantic correctness verification (currently only constitutional admissibility)
- GitHub Actions CI with automated coverage reporting

---

## Quick Start

```bash
git clone https://github.com/LabyrinthCoder/labyrinth-os-core.git
cd labyrinth-os-core
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python run_all.py
python sentinel_core.py
```

**Usage:**

```python
from sentinel_core import SentinelCore

core = SentinelCore()

result = core.process(
    proposal_id = "p001",
    content     = "Execute system update procedure",
    sensor_data = {
        "tau":        0.88,   # escape probability     higher = safer
        "chi":        0.04,   # contradiction risk      lower = safer
        "drift":      0.02,   # distribution drift      lower = safer
        "betti_1":    0.01,   # topological complexity  lower = safer
        "confidence": 0.91,   # overall confidence     higher = safer
    },
)

print(result.decision)      # EXECUTE / BLOCK / KILL
print(result.chain_hash)    # tamper-evident receipt

valid, report = core.replay()
print(report["verdict"])    # CLEAN / VIOLATED
```

**Run with full promotion protocol:**
```bash
LABYRINTH_MODE=full python sentinel_core.py
```

> **Note:** Single-repo prototype layout — not yet packaged as a PyPI installable.
> Modules use local `sys.path` injection. See `KNOWN_GAPS.md` GAP-GH-01.

---

## What Is Formally Proven vs What Is Tested

| Claim | Evidence | File |
|-------|----------|------|
| Sigma Anchor thresholds are internally consistent | **Z3 SMT proof** (A021) | `proofs/sigma_anchors.py` |
| Promotion rules are non-contradictory | **Z3 SMT proofs** PR1–PR8 | `proofs/z3_promotion_proof.py` |
| Predicate invariants hold | **Z3 SMT proofs** PP1–PP9 | `proofs/z3_predicate_proof.py` |
| Pipeline ordering enforced | 1,102 tests · invariants I1–I19 | `epistemic/pipeline_wire.py` |
| Ledger is tamper-evident | Tests — chain breaks on modification | `ledger/hashchain.py` |
| Gate cannot be bypassed | Tests — no code path around gate | `gate/reality_gate.py` |
| Replay is structural | Tests — matches original session | `replay/replay_validator.py` |

> Z3-proven means the threshold constants are mathematically consistent.
> It does not mean the system is safe against all possible inputs.

---

## What This Cannot Do

```
✗  Detect adversarial proposals that stay within threshold values
✗  Block contamination in training data or model weights
✗  Verify semantic correctness — only constitutional admissibility
✗  Operate without sensor data — all five channels are required
✗  Protect against a hostile operator with direct file system access
✗  Replace formal security engineering
```

Full list: [`KNOWN_GAPS.md`](KNOWN_GAPS.md) · [`PRODUCTION_BOUNDARY.md`](PRODUCTION_BOUNDARY.md)

---

## Repository Structure

```
labyrinth-os-core/
│
├── sentinel_core.py          main runtime — start here
├── run_all.py                test suite (1,102 tests)
├── requirements.txt          z3-solver + hypothesis
│
├── proofs/                   Z3 formally verified components
├── epistemic/                labeling, types, pipeline ordering
├── gate/                     the single mandatory crossing point
├── cgir/                     typed intermediate representation
├── execution/                gate decisions, watchers, council
├── ledger/                   tamper-evident audit chain
├── replay/                   session replay and verification
├── governance/               promotion protocol and rules
├── memory/                   archive, feedback, learning
├── observability/            metrics, drift, anomaly detection
├── system/                   snapshot and sandbox
└── tests/                    all 25+ test files
```

---

## Where This Fits

```
Labyrinth-OS  (full research system · 1,556 tests)
    │
    └──▶  Sentinel-Core  ◀── this repository
              │
              └──▶  Agent Layer  (robot + agent deployment · 679 tests)
                        │
                        └──▶  Portable  (mobile app · 200 tests)
```

---

## Design Philosophy

*This section is for those interested in the conceptual framing. Skip it freely — the system runs without it.*

Most AI governance work asks: *how do we make the model want to be safe?*

This project asks a different question: *how do we make the structure between the model and the world enforce accountability — regardless of what the model wants?*

The constitutional execution doctrine is not about trust — it is about proof. Every decision is logged before it executes. The ledger does not forget. The gate does not negotiate.

PAUSE is the most important gate state. Not EXECUTE, not BLOCK — PAUSE. The moment a system can say *"something is ambiguous, I am holding for a human decision"* instead of forcing a binary — that is when governance becomes real.

The Ω symbol marks agents in this ecosystem. Not because they are magical — because they are replaceable. Any agent can be replaced. The substrate continues. The journal system ensures continuity across rotating cognition.

---

## Acknowledgments

**R.A. Poole** — chi aggregate vulnerability correction and spatial density invariant

**S. Delgado** — p=0.948: latent space geometry is indistinguishable between correct reasoning and deception (informs the predicate layer)

**@BioAnkh84** (Echo Root VE · MIT) — the PAUSE gate decision, independently developed

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

Independent researcher · still learning · [@LabyrinthCoder](https://x.com/LabyrinthCoder) on X

*Questions, criticism, and collaboration welcome.*

</div>
