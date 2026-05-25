# Production Boundary — Labyrinth-OS Sentinel-Core

This file defines exactly what is deployable now versus what is experimental.

---

## Runnable Core Prototype (CORE mode)

The following pipeline runs end-to-end with no external dependencies
beyond `z3-solver`:

```
LABELING → ARCHIVE → REALITY GATE → CGIR → SIGMA ANCHOR GATE →
GUARDIAN SLOT → WORM LEDGER → REPLAY VALIDATOR
```

| Component | Status | Basis |
|-----------|--------|-------|
| Sigma Anchor thresholds | Z3-proven consistent | Z3 SMT proof (A021) |
| Pipeline ordering | Test-verified | 1,102 tests, invariants I1-I19 |
| Reality Gate | Test-verified | No bypass path in code |
| CGIR representation | Test-verified | Deterministic canonical hash |
| Guardian Slot decisions | Test-verified | Typed EXECUTE/BLOCK/KILL |
| WORM ledger | Test-verified | SHA-256 chain, thread-safe |
| Replay validator | Test-verified | Structural replay match |

---

## Experimental (FULL mode — set LABYRINTH_MODE=full)

```python
import os
os.environ["LABYRINTH_MODE"] = "full"
from sentinel_core import SentinelCore
```

| Component | Status | What is experimental |
|-----------|--------|---------------------|
| Full Promotion Protocol | Experimental | Stability window + evidence count |
| Watcher Council | Experimental | Two-watcher, strictest-wins |
| ACP-1 Assumption Tracker | Not in Core | Full system only |
| Healing Loop | Not in Core | Full system only |
| Domain Adapters | Not in Core | Full system only |

---

## Honest Capability Table

| Capability | Available |
|------------|----------|
| Deterministic local runtime | Yes |
| Replayable hash chain | Yes |
| Z3 threshold consistency proofs | Yes |
| Adversarial hardening | No |
| Distributed production deployment | No |
| Semantic truth verification | No |
| Hostile-operator protection | No |
| PyPI-installable package | No — future work |

---

## What "Runnable Prototype" Means Here

- Runs without mocks
- Tests pass without environment-dependent failures
- Behavior is deterministic and replayable
- Claims are test-verified or Z3-proven
- Limitations are documented in `KNOWN_GAPS.md`

## What It Does Not Mean

- Not hardened against adversarial operators
- Not formally verified end-to-end (only threshold constants are Z3-proven)
- Not production-scale — single-process, no distributed execution
- Not a replacement for formal security review

---

*@LabyrinthCoder — sole authority*
*Prototype boundaries documented honestly, May 2026*
