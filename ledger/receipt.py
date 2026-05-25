"""
receipt.py — Labyrinth-OS v6.0
=====================================
Closes Section C gap: ledger/receipt.py
Immutable receipt dataclass for the WORM ledger.

A Receipt is the atomic unit of the Labyrinth-OS ledger. Every verified
action, evaluation, or state transition produces a Receipt that is:
  - Immutable after creation (frozen dataclass pattern)
  - Self-hashing (SHA-256 of canonical content)
  - Timestamp-anchored (UTC epoch)
  - Chain-ready (prev_hash field for hashchain linking)

Receipts are consumed by hashchain.py to form an append-only,
tamper-evident log. They are also written to the Chronicle
(chronicle_query.py) for queryable persistence.

Dependencies: Python standard library only.
"""

import hashlib
import json
import time
import copy


# ─── RECEIPT CLASS ───────────────────────────────────────────────────

class Receipt:
    """
    Immutable ledger receipt.
    
    Once created, a Receipt's fields cannot be modified. The hash
    is computed at creation time from the canonical JSON representation
    of all content fields (excluding the hash itself and prev_hash,
    which are structural).
    
    Fields:
        receipt_id   — Unique identifier (typically "<module>:<sequence>")
        module       — Source module that generated this receipt
        action       — What happened ("EVALUATE", "BASELINE", "VERIFY", etc.)
        verdict      — Outcome ("NOMINAL", "KILL", "BLOCK", "EXECUTE", etc.)
        payload      — Arbitrary dict of action-specific data
        timestamp    — UTC epoch seconds (float)
        prev_hash    — SHA-256 of the previous receipt in the chain ("0"*64 for genesis)
        hash         — SHA-256 of this receipt's canonical content
    """
    
    __slots__ = (
        "_receipt_id", "_module", "_action", "_verdict",
        "_payload", "_timestamp", "_prev_hash", "_hash", "_frozen",
    )
    
    def __init__(
        self,
        receipt_id: str,
        module: str,
        action: str,
        verdict: str,
        payload: dict = None,
        timestamp: float = None,
        prev_hash: str = None,
    ):
        object.__setattr__(self, "_frozen", False)
        self._receipt_id = receipt_id
        self._module = module
        self._action = action
        self._verdict = verdict
        self._payload = copy.deepcopy(payload) if payload else {}
        self._timestamp = timestamp if timestamp is not None else time.time()
        self._prev_hash = prev_hash or ("0" * 64)
        self._hash = self._compute_hash()
        object.__setattr__(self, "_frozen", True)
    
    # ── Properties (read-only access) ──
    
    @property
    def receipt_id(self):
        return self._receipt_id
    
    @property
    def module(self):
        return self._module
    
    @property
    def action(self):
        return self._action
    
    @property
    def verdict(self):
        return self._verdict
    
    @property
    def payload(self):
        return copy.deepcopy(self._payload)
    
    @property
    def timestamp(self):
        return self._timestamp
    
    @property
    def prev_hash(self):
        return self._prev_hash
    
    @property
    def hash(self):
        return self._hash
    
    # ── Immutability enforcement ──
    
    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Receipt is immutable: cannot set '{name}'")
        object.__setattr__(self, name, value)
    
    def __delattr__(self, name):
        raise AttributeError(f"Receipt is immutable: cannot delete '{name}'")
    
    # ── Hashing ──
    
    def _compute_hash(self):
        """Compute SHA-256 of canonical content."""
        canonical = self._canonical_dict()
        content = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    def _canonical_dict(self):
        """Content fields used for hashing (excludes hash itself)."""
        return {
            "receipt_id": self._receipt_id,
            "module": self._module,
            "action": self._action,
            "verdict": self._verdict,
            "payload": self._payload,
            "timestamp": self._timestamp,
            "prev_hash": self._prev_hash,
        }
    
    def verify(self):
        """Verify that the stored hash matches recomputed hash."""
        return self._hash == self._compute_hash()
    
    # ── Serialization ──
    
    def to_dict(self):
        """Full serialization including hash."""
        d = self._canonical_dict()
        d["hash"] = self._hash
        return d
    
    def to_json(self, indent=None):
        """JSON string representation."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent)
    
    @classmethod
    def from_dict(cls, d):
        """Reconstruct a Receipt from a dict. Validates hash integrity."""
        r = cls(
            receipt_id=d["receipt_id"],
            module=d["module"],
            action=d["action"],
            verdict=d["verdict"],
            payload=d.get("payload", {}),
            timestamp=d["timestamp"],
            prev_hash=d.get("prev_hash", "0" * 64),
        )
        if "hash" in d and r.hash != d["hash"]:
            raise ValueError(
                f"Hash mismatch: computed {r.hash[:16]}... != stored {d['hash'][:16]}..."
            )
        return r
    
    @classmethod
    def from_json(cls, json_str):
        """Reconstruct from JSON string."""
        return cls.from_dict(json.loads(json_str))
    
    # ── Display ──
    
    def __repr__(self):
        return (
            f"Receipt(id={self._receipt_id!r}, module={self._module!r}, "
            f"action={self._action!r}, verdict={self._verdict!r}, "
            f"hash={self._hash[:16]}...)"
        )
    
    def __eq__(self, other):
        if not isinstance(other, Receipt):
            return NotImplemented
        return self._hash == other._hash
    
    def __hash__(self):
        return hash(self._hash)


# ─── FACTORY FUNCTIONS ───────────────────────────────────────────────

def genesis_receipt(module="labyrinth", payload=None):
    """Create the genesis (first) receipt in a chain."""
    return Receipt(
        receipt_id=f"{module}:genesis",
        module=module,
        action="GENESIS",
        verdict="NOMINAL",
        payload=payload or {"version": " v6.0"},
        prev_hash="0" * 64,
    )


def evaluation_receipt(module, verdict, metrics, prev_hash, seq=0):
    """Create a receipt for a guardian/pipeline evaluation."""
    return Receipt(
        receipt_id=f"{module}:eval:{seq}",
        module=module,
        action="EVALUATE",
        verdict=verdict,
        payload=metrics,
        prev_hash=prev_hash,
    )


def verification_receipt(module, file_hash, test_count, prev_hash, seq=0):
    """Create a receipt for a module verification (forge test pass)."""
    return Receipt(
        receipt_id=f"{module}:verify:{seq}",
        module=module,
        action="VERIFY",
        verdict="PASS",
        payload={"file_sha256": file_hash, "tests_passed": test_count},
        prev_hash=prev_hash,
    )


# ─── TEST SUITE ──────────────────────────────────────────────────────

def _test_basic_creation():
    """Receipt can be created with required fields."""
    r = Receipt("test:0", "test_module", "TEST", "NOMINAL", timestamp=1000.0)
    assert r.receipt_id == "test:0"
    assert r.module == "test_module"
    assert r.action == "TEST"
    assert r.verdict == "NOMINAL"
    assert r.timestamp == 1000.0
    return True


def _test_hash_is_64_hex():
    """Hash is a 64-char hex SHA-256."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    assert len(r.hash) == 64
    assert all(c in "0123456789abcdef" for c in r.hash)
    return True


def _test_hash_deterministic():
    """Same inputs → same hash."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", payload={"x": 1}, timestamp=1000.0)
    r2 = Receipt("test:0", "mod", "ACT", "OK", payload={"x": 1}, timestamp=1000.0)
    assert r1.hash == r2.hash
    return True


def _test_hash_changes_with_content():
    """Different content → different hash."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    r2 = Receipt("test:1", "mod", "ACT", "OK", timestamp=1000.0)
    assert r1.hash != r2.hash
    return True


def _test_immutable_after_creation():
    """Cannot modify receipt fields after creation."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    try:
        r._receipt_id = "tampered"
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass
    return True


def _test_cannot_delete_fields():
    """Cannot delete receipt fields."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    try:
        del r._receipt_id
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass
    return True


def _test_payload_deep_copy():
    """Payload is deep-copied; external mutations don't affect receipt."""
    original = {"nested": {"value": 1}}
    r = Receipt("test:0", "mod", "ACT", "OK", payload=original, timestamp=1000.0)
    original["nested"]["value"] = 999
    assert r.payload["nested"]["value"] == 1
    return True


def _test_payload_getter_returns_copy():
    """Payload getter returns a copy, not the internal reference."""
    r = Receipt("test:0", "mod", "ACT", "OK", payload={"x": 1}, timestamp=1000.0)
    p = r.payload
    p["x"] = 999
    assert r.payload["x"] == 1
    return True


def _test_verify_passes_on_valid():
    """verify() returns True for an untampered receipt."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    assert r.verify() is True
    return True


def _test_default_prev_hash():
    """Default prev_hash is 64 zeros (genesis marker)."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    assert r.prev_hash == "0" * 64
    return True


def _test_prev_hash_included_in_hash():
    """Different prev_hash → different receipt hash."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", prev_hash="0" * 64, timestamp=1000.0)
    r2 = Receipt("test:0", "mod", "ACT", "OK", prev_hash="a" * 64, timestamp=1000.0)
    assert r1.hash != r2.hash
    return True


def _test_to_dict_roundtrip():
    """to_dict → from_dict produces equal receipt."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", payload={"k": "v"}, timestamp=1000.0)
    d = r1.to_dict()
    r2 = Receipt.from_dict(d)
    assert r1 == r2
    assert r1.hash == r2.hash
    return True


def _test_to_json_roundtrip():
    """to_json → from_json produces equal receipt."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", payload={"n": 42}, timestamp=1000.0)
    j = r1.to_json()
    r2 = Receipt.from_json(j)
    assert r1 == r2
    return True


def _test_from_dict_detects_tamper():
    """from_dict raises ValueError if hash doesn't match."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    d = r.to_dict()
    d["verdict"] = "TAMPERED"  # Modify content without updating hash
    try:
        Receipt.from_dict(d)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    return True


def _test_equality_by_hash():
    """Two receipts with same hash are equal."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    r2 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    assert r1 == r2
    return True


def _test_inequality():
    """Two receipts with different content are not equal."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    r2 = Receipt("test:1", "mod", "ACT", "OK", timestamp=1000.0)
    assert r1 != r2
    return True


def _test_hashable():
    """Receipts can be used in sets and as dict keys."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    r2 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    s = {r1, r2}
    assert len(s) == 1
    return True


def _test_repr():
    """repr includes key fields."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    s = repr(r)
    assert "test:0" in s
    assert "mod" in s
    assert "ACT" in s
    return True


def _test_genesis_factory():
    """genesis_receipt produces valid genesis receipt."""
    r = genesis_receipt("labyrinth")
    assert r.receipt_id == "labyrinth:genesis"
    assert r.action == "GENESIS"
    assert r.prev_hash == "0" * 64
    assert r.verify()
    return True


def _test_evaluation_factory():
    """evaluation_receipt produces valid evaluation receipt."""
    r = evaluation_receipt(
        "guardian_slot", "EXECUTE",
        {"tau": 0.9, "drift": 0.02},
        prev_hash="a" * 64, seq=1,
    )
    assert r.receipt_id == "guardian_slot:eval:1"
    assert r.action == "EVALUATE"
    assert r.verdict == "EXECUTE"
    assert r.prev_hash == "a" * 64
    assert r.verify()
    return True


def _test_verification_factory():
    """verification_receipt produces valid verification receipt."""
    r = verification_receipt(
        "tau_baseline_generator",
        file_hash="abc123",
        test_count=26,
        prev_hash="b" * 64,
    )
    assert r.action == "VERIFY"
    assert r.verdict == "PASS"
    assert r.payload["tests_passed"] == 26
    assert r.verify()
    return True


def _test_empty_payload():
    """Receipt with no payload works correctly."""
    r = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    assert r.payload == {}
    assert r.verify()
    return True


def _test_large_payload():
    """Receipt handles large payloads."""
    big = {f"key_{i}": f"value_{i}" for i in range(1000)}
    r = Receipt("test:0", "mod", "ACT", "OK", payload=big, timestamp=1000.0)
    assert len(r.payload) == 1000
    assert r.verify()
    return True


def _test_nested_payload():
    """Receipt handles deeply nested payloads."""
    nested = {"a": {"b": {"c": {"d": [1, 2, 3]}}}}
    r = Receipt("test:0", "mod", "ACT", "OK", payload=nested, timestamp=1000.0)
    assert r.payload["a"]["b"]["c"]["d"] == [1, 2, 3]
    assert r.verify()
    return True


def _test_chain_linking():
    """Receipts can be chained via prev_hash."""
    r1 = Receipt("test:0", "mod", "ACT", "OK", timestamp=1000.0)
    r2 = Receipt("test:1", "mod", "ACT", "OK", prev_hash=r1.hash, timestamp=1001.0)
    r3 = Receipt("test:2", "mod", "ACT", "OK", prev_hash=r2.hash, timestamp=1002.0)
    assert r2.prev_hash == r1.hash
    assert r3.prev_hash == r2.hash
    assert r1.verify() and r2.verify() and r3.verify()
    return True


# ─── TEST RUNNER ─────────────────────────────────────────────────────

def run_tests():
    tests = [(name, obj) for name, obj in globals().items()
             if name.startswith("_test_") and callable(obj)]
    tests.sort(key=lambda x: x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            results.append((name, "PASS", None))
        except Exception as e:
            failed += 1
            results.append((name, "FAIL", str(e)))
    return passed, failed, results


if __name__ == "__main__":
    print("=" * 70)
    print("RECEIPT — Labyrinth-OS v6.0")
    print("=" * 70)
    
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err:
            line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    
    if failed > 0:
        raise SystemExit(1)
    
    # Demo
    print("\n── DEMO ──\n")
    g = genesis_receipt()
    print(f"  Genesis: {g}")
    e = evaluation_receipt("guardian_slot", "EXECUTE", {"tau": 0.9}, g.hash, seq=1)
    print(f"  Eval:    {e}")
    v = verification_receipt("tau_baseline", "abc123", 26, e.hash, seq=1)
    print(f"  Verify:  {v}")
    print(f"  Chain:   genesis → eval → verify")
    print(f"           {g.hash[:16]}... → {e.hash[:16]}... → {v.hash[:16]}...")
    
    import hashlib as _hl
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {fh}")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Section C gap: ledger/receipt.py — CLOSED")
    print(f"{'=' * 70}")
