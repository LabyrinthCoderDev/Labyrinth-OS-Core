# Labyrinth OS · Core

<p align="center">
  <img src="https://img.shields.io/badge/Status-Experimental%20Prototype-orange?style=for-the-badge" alt="Status: Experimental Prototype"/>
  <img src="https://img.shields.io/badge/Tests-1%2C102%20Passing-brightgreen?style=for-the-badge" alt="Tests: 1,102 Passing"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"/>
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge" alt="Python: 3.11+"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Z3%20Proofs-A021%20%7C%20PR1--PR8%20%7C%20PP1--PP9-purple?style=for-the-badge" alt="Z3 Proofs"/>
  <img src="https://img.shields.io/badge/Author-%40LabyrinthCoder-teal?style=for-the-badge&logo=x" alt="@LabyrinthCoder"/>
</p>

<p align="center">
  <strong><em>"Imagination is free. Execution requires proof. No exception."</em></strong>
</p>

---

<p align="center">
The constitutional enforcement kernel for AI systems.<br/>
A formal gate between what a model <em>proposes</em> and what it is allowed to <em>execute</em>.<br/>
Independent research. Experimental prototype. Scrutiny welcomed.
</p>

---

## What This Is

This is the deployable kernel of a larger personal research project called **Labyrinth OS** — a constitutional enforcement layer for AI systems.

I am an independent developer, still learning. This is not a production system and I am not claiming it is. What it is: a working prototype of an idea I have been building and testing for several months. The core idea is that **an AI system should not be able to act without passing through a formal gate** — and that gate decision should be logged, chained, and replayable.

This repository is the smallest version of that idea that actually runs.

> **This is a fragment of a larger system.** The full Labyrinth OS has 1,556 tests across multiple deployment surfaces. This is the constitutional kernel that everything else is built on top of.

---

## The Idea

Most AI safety work asks: *how do we make the model want to be safe?*

This project asks a different question: *how do we make the structure between the model and the world enforce safety regardless of what the model wants?*

```
┌─────────────────────────────────────────────────────────┐
│                    LANE 1 (Epistemic)                    │
│         The model proposes. Nothing executes here.       │
└─────────────────────────┬───────────────────────────────┘
                          │
                    REALITY GATE
                    (one crossing point)
                    TRUTH + evidence + no contradiction
                          │
┌─────────────────────────▼───────────────────────────────┐
│                    LANE 2 (Execution)                    │
│    Gate-approved proposals only. Every decision logged.  │
└─────────────────────────────────────────────────────────┘
```

The gate is not advisory. It is the only path between the two lanes.

---

## The Pipeline

Every proposal passes through this sequence. Nothing bypasses any stage.

```
INPUT
  │
  ▼
LABELING ──────────── classify the proposal epistemically
  │
  ▼
ARCHIVE ───────────── store immutably before evaluation
  │
  ▼
REALITY GATE ─────── single mandatory crossing point
  │                   TRUTH + evidence + no contradiction required
  ▼
CGIR TRANSLATION ──── typed intermediate representation
  │                   canonical hash, insertion-order independent
  ▼
SIGMA ANCHOR GATE ─── five-channel threshold check
  │                   τ (escape) · χ (contradiction) · drift
  │                   β₁ (topology) · confidence
  │                   thresholds Z3-formally-proven (A021)
  ▼
GUARDIAN SLOT ──────── final typed decision
  │                   EXECUTE · BLOCK · KILL
  ▼
WORM LEDGER ────────── SHA-256 hash chain
  │                   append-only · tamper-evident · thread-safe
  ▼
REPLAY VALIDATOR ───── structural replay verification
                       CLEAN · VIOLATED
```

---

## What Is Formally Proven vs What Is Tested

I want to be specific about this because it matters.

| Claim | How it's supported | File |
|-------|-------------------|------|
| Sigma Anchor thresholds are internally consistent | **Z3 SMT proof** (A021) | `sigma_anchors.py` |
| Promotion rules are non-contradictory | **Z3 SMT proofs** PR1-PR8 | `z3_promotion_proof.py` |
| Predicate invariants hold | **Z3 SMT proofs** PP1-PP9 | `z3_predicate_proof.py` |
| Pipeline ordering is enforced | 1,102 tests, invariants I1-I19 | `pipeline_wire.py` |
| Ledger is tamper-evident | Tests — SHA-256 chain breaks on modification | `hashchain.py` |
| Gate cannot be bypassed in code | Tests — no path around `reality_gate.py` | `reality_gate.py` |
| Replay is exact | Tests — structural replay matches original | `replay_validator.py` |

Z3-proven means the *threshold constants* are consistent with each other mathematically. It does not mean the system is safe against all possible inputs. See **What This Cannot Do** below.

---

## Quick Start

```bash
git clone https://github.com/LabyrinthCoder/labyrinth-os-core.git
cd labyrinth-os-core
pip install z3-solver
python run_all.py          # 1,102 tests
python sentinel_core.py    # self-test + demo
```

**Usage:**

```python
from sentinel_core import SentinelCore

core = SentinelCore()

result = core.process(
    proposal_id = "p001",
    content     = "Execute system update procedure",
    sensor_data = {
        "tau":        0.88,   # escape probability  — higher is safer
        "chi":        0.04,   # contradiction risk   — lower is safer
        "drift":      0.02,   # distribution drift   — lower is safer
        "betti_1":    0.01,   # topological complexity — lower is safer
        "confidence": 0.91,   # overall confidence   — higher is safer
    },
)

print(result.decision)      # EXECUTE / BLOCK / KILL
print(result.chain_hash)    # tamper-evident receipt

# Verify the full session chain
valid, report = core.replay()
print(report["verdict"])    # CLEAN / VIOLATED
```

---

## What This Cannot Do

Being specific about limitations is part of the project.

- It **cannot** detect a well-crafted adversarial proposal whose sensor readings stay within thresholds — the gate trusts the sensor values it receives
- It **cannot** block pre-execution contamination in training data or model weights
- It **cannot** verify semantic correctness — only constitutional admissibility
- It **cannot** run without sensor data — the five channels are required inputs
- It is **not** hardened against a hostile operator with direct file access
- It is **not** a replacement for formal security engineering

The full taxonomy of what is and is not proven is in `KNOWN_GAPS.md`.

---

## Key Files

```
sentinel_core.py        main runtime — start here
sigma_anchors.py        Z3-proven threshold constants (A021)
pipeline_wire.py        constitutional pipeline ordering
reality_gate.py         single mandatory Lane 1 → Lane 2 crossing
cgir_gate.py            Sigma Anchor five-channel gate
guardian_slot.py        final EXECUTE / BLOCK / KILL decision
hashchain.py            WORM SHA-256 hash chain
cgir_ledger.py          session ledger
replay_validator.py     structural replay verification
run_all.py              test suite (1,102 tests)
KNOWN_GAPS.md           honest list of open items
SNAPSHOT.md             full file inventory and proof table
```

---

## Where This Fits

```
Labyrinth OS (full system, 1,556 tests)
  └── Core  ◄── this repository
        └── Agent Layer (679 tests, agent deployment)
              └── Portable (200 tests, mobile)
```

Core is the constitutional substrate. The layers above it add domain-specific adapters, healing loops, governance protocols, and deployment surfaces. None of those layers weaken what is here — they extend it.

---

## Acknowledgments

**R.A. Poole** — two direct technical contributions to this build:
- Chi aggregate vulnerability correction (`cgir_guardian_bridge.py`)
- Spatial density invariant pattern (`physics_sentinel.py`)

**S. Delgado** — research finding that informs the predicate layer:
- p=0.948: latent space geometry is indistinguishable between correct reasoning and deception
- This finding underlies the second verification axis (Φ1/Φ2/Φ3) via Z3

**@BioAnkh84** (Echo Root VE, MIT License) — the PAUSE gate state.
Two systems built independently in different domains converged on the same architecture.
The PAUSE decision — hold execution when signals are ambiguous — came from that work.

---

## License

MIT — see [LICENSE](LICENSE)

---

## Contact

Independent researcher, still learning.

**@LabyrinthCoder** on X — open to questions, criticism, and collaboration.
