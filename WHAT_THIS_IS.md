# WHAT THIS IS
## Sentinel-Core — Deployable Kernel

**This is the minimal deployable version of Labyrinth-OS.**

When you open this ZIP or TXT, you are reading 19 files that represent
everything that fully works right now — no stubs, no PARTIAL gaps, no mocks.

---

## One-Line Summary

**Import SentinelCore, pass sensor readings, get EXECUTE/BLOCK/KILL. Done.**

---

## Three Systems — Which One Are You Looking At?

| File Name | What It Is | Tests |
|-----------|-----------|-------|
| `Labyrinth-OS.zip / .txt` | Full research system — everything | 1,556 |
| `Labyrinth-OS-Agent.zip` | Agent deployment layer | 679 |
| `Labyrinth-OS-Core.zip / .txt` | **THIS FILE** — Deployable kernel | 1,102 |

---

## Usage

```python
from sentinel_core import SentinelCore

core = SentinelCore()
result = core.process(
    proposal_id = "p001",
    content     = "Execute system update",
    sensor_data = {"tau": 0.88, "chi": 0.04, "drift": 0.02,
                   "betti_1": 0.01, "confidence": 0.91},
)
print(result.decision)   # EXECUTE / BLOCK / KILL
valid, report = core.replay()
print(report["verdict"]) # CLEAN
```

---

## What Is Proven

- Sigma Anchor thresholds: **Z3-PROVEN** (A021)
- Pipeline ordering: **TEST-VERIFIED** (I1-I19)
- Ledger tamper-evidence: **TEST-VERIFIED**
- Exact replay: **TEST-VERIFIED**
- Gate cannot be bypassed: **TEST-VERIFIED**

---

## Contact

X: @LabyrinthCoder
