# KNOWN GAPS — Labyrinth-OS-Core
## Labyrinth OS · Core | May 2026 | @LabyrinthCoder

This file lists every known gap, open item, and honest limitation
in the current build. It is public and intentional.

"We log what we built. Timestamps speak."

---

## STATUS DEFINITIONS

| Status | Meaning |
|--------|---------|
| OPEN | Not yet addressed. Documented as known risk. |
| PARTIAL | Partially mitigated. Residual risk documented. |
| WIRED | Implemented and tested. |
| ENV | Environment limitation — not a code gap. |

---

## OPS-CORE-001 — Epistemic Labeller Sync

**Status:** OPEN
**What:** Portable v15 epistemic labeller (no-KILL variant) not yet synced to Core.
**Impact:** Core uses prior labeller version. No functional regression — labels still correct.
**Fix:** Sync from Portable v15 epistemic_labeler.py when directed.

---

## OPS-CORE-002 — betti_1 Structural Proxy

**Status:** OPEN
**What:** betti_1 proxy from Portable v15 not yet synced to Core.
**Impact:** betti_1 returns structural proxy value. Documented in SNAPSHOT.md.
**Fix:** Sync when directed.

---

## OPS-CORE-003 — LICENSE

**Status:** WIRED (see LICENSE file)


---

## GITHUB-FACING GAPS (Added May 2026)

### GAP-GH-01: Package/import layout not PyPI-grade
**Status:** OPEN
Modules use sys.path injection. Not yet installable via `pip install`.
Functional for local use. Packaging as a proper Python package is future work.

### GAP-GH-02: Semantic correctness not verified
**Status:** OPEN — by design
The gate enforces constitutional admissibility, not semantic truth.
A proposal can be structurally valid and constitutionally admitted
while being semantically wrong. This is documented and intentional.

### GAP-GH-03: Sensor values are trusted inputs
**Status:** OPEN — by design
The system trusts the five sensor channels it receives.
An adversary who controls the sensor scoring bypasses the gate.
Documented in THREAT_MODEL and PRODUCTION_BOUNDARY.md.

### GAP-GH-04: No hostile-operator hardening
**Status:** OPEN
Direct file system access by a malicious operator bypasses all controls.
Single trusted-operator deployment only.

### GAP-GH-05: No distributed/concurrent production runtime
**Status:** OPEN
The WORM ledger is thread-safe. The system is not designed for
distributed multi-node execution.

### GAP-GH-06: Rust parity tests are conditional
**Status:** DOCUMENTED
test_rust_python_differential.py and test_rust_python_parity.py
return True (pass) when Rust crates are absent.
Rust crates are not included in Sentinel-Core.
This is by design — Core is Python-only.

---

*@LabyrinthCoder — sole authority*
*Updated: May 2026*
