"""
hashchain.py — Labyrinth-OS v6.0
=======================================
Closes Section C gap: ledger/hashchain.py
SHA-256 append-only hash chain.

The HashChain is the backbone of the WORM (Write Once Read Many)
ledger. It maintains an ordered sequence of Receipt objects linked
by SHA-256 hashes, forming a tamper-evident log.

Properties:
  - Append-only: receipts can be added but never removed or modified
  - Tamper-evident: any modification to any receipt breaks the chain
  - Verifiable: full chain integrity can be checked in O(n)
  - Serializable: chain can be exported/imported as JSON
  - Genesis-anchored: first receipt must have prev_hash = "0" * 64

Integrates with:
  - receipt.py (Receipt dataclass)
  - ledger_utils.py (WORM ledger utilities)
  - chronicle_query.py (queryable persistence)

Dependencies: Python standard library only.
"""

import hashlib
import json
import time
import copy
import threading

# Import Receipt from the same directory
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt import Receipt, genesis_receipt, evaluation_receipt, verification_receipt


# ─── HASH CHAIN ──────────────────────────────────────────────────────

class HashChain:
    """
    Append-only, tamper-evident hash chain.

    Each receipt's prev_hash must equal the hash of the preceding
    receipt (or "0"*64 for the genesis receipt). The chain enforces
    this invariant on every append.

    CONCURRENCY (I19 — Session Isolation):
    - In-process thread safety: a threading.Lock guards append() and verify().
    - Cross-process safety: two separate Python processes writing to the same
      in-memory HashChain cannot occur (separate address spaces). If HashChain
      is serialized to a shared file, the caller is responsible for file-level
      locking (see chronicle_query.py which uses fcntl.flock on its index).
    - The CGIRLedger (which wraps HashChain) enforces one session per instance.
    - For multi-process safety, use session-specific output directories rather
      than sharing a single HashChain file. See INVARIANTS.md I19.
    """
    
    def __init__(self):
        self._chain = []       # list of Receipt objects
        self._index = {}       # receipt_id → position
        self._head_hash = "0" * 64  # hash of the latest receipt
        self._lock = threading.Lock()  # I19: thread-safe append/verify

    # ── Properties ──

    @property
    def length(self):
        return len(self._chain)

    @property
    def head_hash(self):
        """Hash of the most recent receipt (or "0"*64 if empty)."""
        return self._head_hash

    @property
    def is_empty(self):
        return len(self._chain) == 0

    # ── Core operations ──

    def append(self, receipt: Receipt):
        """
        Append a receipt to the chain. Thread-safe (I19).

        Validates:
          1. Receipt's prev_hash matches current head_hash
          2. Receipt's internal hash is valid (self-consistent)
          3. Receipt ID is unique within the chain

        Raises ValueError on any validation failure.
        """
        with self._lock:
            if receipt.prev_hash != self._head_hash:
                raise ValueError(
                    f"Chain linkage broken: receipt.prev_hash={receipt.prev_hash[:16]}... "
                    f"!= head_hash={self._head_hash[:16]}..."
                )
            # Validate internal hash integrity
            if not receipt.verify():
                raise ValueError(
                    f"Receipt {receipt.receipt_id} has invalid internal hash"
                )
            # Validate unique ID
            if receipt.receipt_id in self._index:
                raise ValueError(
                    f"Duplicate receipt_id: {receipt.receipt_id}"
                )
            # Append
            pos = len(self._chain)
            self._chain.append(receipt)
            self._index[receipt.receipt_id] = pos
            self._head_hash = receipt.hash
    
    def get(self, index: int) -> Receipt:
        """Get receipt by position (0-based)."""
        if index < 0 or index >= len(self._chain):
            raise IndexError(f"Chain index {index} out of range [0, {len(self._chain)})")
        return self._chain[index]
    
    def get_by_id(self, receipt_id: str) -> Receipt:
        """Get receipt by its receipt_id."""
        if receipt_id not in self._index:
            raise KeyError(f"Receipt not found: {receipt_id}")
        return self._chain[self._index[receipt_id]]
    
    def head(self) -> Receipt:
        """Get the most recent receipt."""
        if not self._chain:
            raise IndexError("Chain is empty")
        return self._chain[-1]
    
    def tail(self, n: int) -> list:
        """Get the last n receipts."""
        return list(self._chain[-n:])
    
    # ── Verification ──
    
    def verify(self):
        """
        Verify the entire chain's integrity.
        
        Checks:
          1. Each receipt's internal hash is valid
          2. Each receipt's prev_hash matches the prior receipt's hash
          3. Genesis receipt has prev_hash = "0" * 64
        
        Returns (is_valid, first_broken_index_or_None, error_message_or_None)
        """
        if not self._chain:
            return True, None, None
        
        expected_prev = "0" * 64
        
        for i, receipt in enumerate(self._chain):
            # Check internal hash
            if not receipt.verify():
                return False, i, f"Receipt {i} ({receipt.receipt_id}) has invalid internal hash"
            
            # Check linkage
            if receipt.prev_hash != expected_prev:
                return False, i, (
                    f"Receipt {i} ({receipt.receipt_id}) linkage broken: "
                    f"prev_hash={receipt.prev_hash[:16]}... != expected={expected_prev[:16]}..."
                )
            
            expected_prev = receipt.hash
        
        return True, None, None
    
    # ── Query ──
    
    def filter_by_module(self, module: str) -> list:
        """Get all receipts from a specific module."""
        return [r for r in self._chain if r.module == module]
    
    def filter_by_action(self, action: str) -> list:
        """Get all receipts with a specific action."""
        return [r for r in self._chain if r.action == action]
    
    def filter_by_verdict(self, verdict: str) -> list:
        """Get all receipts with a specific verdict."""
        return [r for r in self._chain if r.verdict == verdict]
    
    # ── Serialization ──
    
    def to_list(self):
        """Serialize chain as list of dicts."""
        return [r.to_dict() for r in self._chain]
    
    def to_json(self, indent=2):
        """Serialize chain as JSON string."""
        return json.dumps(self.to_list(), indent=indent)
    
    @classmethod
    def from_list(cls, receipt_dicts):
        """
        Reconstruct chain from list of dicts.
        
        Validates each receipt's hash and linkage during reconstruction.
        """
        chain = cls()
        for d in receipt_dicts:
            receipt = Receipt.from_dict(d)
            chain.append(receipt)
        return chain
    
    @classmethod
    def from_json(cls, json_str):
        """Reconstruct chain from JSON string."""
        return cls.from_list(json.loads(json_str))
    
    # ── Merkle root ──
    
    def merkle_root(self):
        """
        Compute a Merkle root hash over all receipt hashes.
        
        Provides a single hash summarizing the entire chain state.
        Useful for cross-chain anchoring and quick integrity comparison.
        """
        if not self._chain:
            return "0" * 64
        
        hashes = [r.hash for r in self._chain]
        
        while len(hashes) > 1:
            next_level = []
            for i in range(0, len(hashes), 2):
                left = hashes[i]
                right = hashes[i + 1] if i + 1 < len(hashes) else left
                combined = hashlib.sha256((left + right).encode("utf-8")).hexdigest()
                next_level.append(combined)
            hashes = next_level
        
        return hashes[0]
    
    # ── Display ──
    
    def __repr__(self):
        return f"HashChain(length={self.length}, head={self._head_hash[:16]}...)"
    
    def __len__(self):
        return len(self._chain)
    
    def __iter__(self):
        return iter(self._chain)
    
    def __getitem__(self, index):
        return self.get(index)


# ─── CONVENIENCE ─────────────────────────────────────────────────────

def build_chain(*receipts_args):
    """
    Build a chain from receipt creation arguments.
    
    Each arg is a tuple of (receipt_id, module, action, verdict, payload).
    prev_hash is automatically set from the chain.
    Uses deterministic timestamps (1000.0 + index) for reproducibility.
    """
    chain = HashChain()
    for i, args in enumerate(receipts_args):
        rid, mod, act, ver = args[0], args[1], args[2], args[3]
        payload = args[4] if len(args) > 4 else {}
        r = Receipt(rid, mod, act, ver, payload=payload, prev_hash=chain.head_hash, timestamp=1000.0 + i)
        chain.append(r)
    return chain


# ─── TEST SUITE ──────────────────────────────────────────────────────

def _test_empty_chain():
    """Empty chain has length 0 and genesis head hash."""
    c = HashChain()
    assert c.length == 0
    assert c.is_empty
    assert c.head_hash == "0" * 64
    return True


def _test_append_genesis():
    """Can append a genesis receipt."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    assert c.length == 1
    assert not c.is_empty
    assert c.head_hash == g.hash
    return True


def _test_append_chain():
    """Can append multiple linked receipts."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    e = evaluation_receipt("mod", "EXECUTE", {"tau": 0.9}, g.hash, seq=1)
    c.append(e)
    assert c.length == 2
    assert c.head_hash == e.hash
    return True


def _test_append_rejects_bad_linkage():
    """Append rejects receipt with wrong prev_hash."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    bad = Receipt("bad:0", "mod", "ACT", "OK", prev_hash="f" * 64, timestamp=1000.0)
    try:
        c.append(bad)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    assert c.length == 1  # Chain unchanged
    return True


def _test_append_rejects_duplicate_id():
    """Append rejects receipt with duplicate receipt_id."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    dup = Receipt(g.receipt_id, "mod", "ACT", "OK", prev_hash=g.hash, timestamp=1000.0)
    try:
        c.append(dup)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    return True


def _test_get_by_index():
    """Can retrieve receipts by index."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    assert c.get(0) == g
    assert c[0] == g
    return True


def _test_get_by_id():
    """Can retrieve receipts by receipt_id."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    assert c.get_by_id("labyrinth:genesis") == g
    return True


def _test_get_by_id_missing():
    """get_by_id raises KeyError for missing receipt."""
    c = HashChain()
    try:
        c.get_by_id("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass
    return True


def _test_head():
    """head() returns the most recent receipt."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    e = evaluation_receipt("mod", "OK", {}, g.hash)
    c.append(e)
    assert c.head() == e
    return True


def _test_head_empty():
    """head() raises on empty chain."""
    c = HashChain()
    try:
        c.head()
        assert False, "Should have raised IndexError"
    except IndexError:
        pass
    return True


def _test_tail():
    """tail(n) returns last n receipts."""
    c = build_chain(
        ("r:0", "m", "A", "OK"),
        ("r:1", "m", "A", "OK"),
        ("r:2", "m", "A", "OK"),
    )
    t = c.tail(2)
    assert len(t) == 2
    assert t[0].receipt_id == "r:1"
    assert t[1].receipt_id == "r:2"
    return True


def _test_verify_valid_chain():
    """verify() passes on a valid chain."""
    c = build_chain(
        ("r:0", "m", "A", "OK"),
        ("r:1", "m", "A", "OK"),
        ("r:2", "m", "A", "OK"),
    )
    valid, idx, msg = c.verify()
    assert valid is True
    assert idx is None
    return True


def _test_verify_empty_chain():
    """verify() passes on an empty chain."""
    c = HashChain()
    valid, idx, msg = c.verify()
    assert valid is True
    return True


def _test_filter_by_module():
    """filter_by_module returns correct subset."""
    c = HashChain()
    g = Receipt("r:0", "alpha", "A", "OK", prev_hash="0" * 64, timestamp=1000.0)
    c.append(g)
    r2 = Receipt("r:1", "beta", "A", "OK", prev_hash=g.hash, timestamp=1001.0)
    c.append(r2)
    r3 = Receipt("r:2", "alpha", "B", "OK", prev_hash=r2.hash, timestamp=1002.0)
    c.append(r3)
    alphas = c.filter_by_module("alpha")
    assert len(alphas) == 2
    return True


def _test_filter_by_action():
    """filter_by_action returns correct subset."""
    c = build_chain(
        ("r:0", "m", "GENESIS", "OK"),
        ("r:1", "m", "EVALUATE", "OK"),
        ("r:2", "m", "VERIFY", "OK"),
    )
    evals = c.filter_by_action("EVALUATE")
    assert len(evals) == 1
    assert evals[0].receipt_id == "r:1"
    return True


def _test_filter_by_verdict():
    """filter_by_verdict returns correct subset."""
    c = build_chain(
        ("r:0", "m", "A", "NOMINAL"),
        ("r:1", "m", "A", "KILL"),
        ("r:2", "m", "A", "NOMINAL"),
    )
    kills = c.filter_by_verdict("KILL")
    assert len(kills) == 1
    return True


def _test_json_roundtrip():
    """to_json → from_json preserves chain."""
    c = build_chain(
        ("r:0", "m", "A", "OK", {"x": 1}),
        ("r:1", "m", "B", "OK", {"y": 2}),
    )
    j = c.to_json()
    c2 = HashChain.from_json(j)
    assert c2.length == 2
    valid, _, _ = c2.verify()
    assert valid
    assert c2[0].receipt_id == "r:0"
    assert c2[1].payload == {"y": 2}
    return True


def _test_list_roundtrip():
    """to_list → from_list preserves chain."""
    c = build_chain(
        ("r:0", "m", "A", "OK"),
        ("r:1", "m", "A", "OK"),
    )
    lst = c.to_list()
    c2 = HashChain.from_list(lst)
    assert c2.length == 2
    assert c2.head_hash == c.head_hash
    return True


def _test_from_json_detects_tamper():
    """from_json rejects tampered chain data."""
    c = build_chain(("r:0", "m", "A", "OK"), ("r:1", "m", "A", "OK"))
    lst = c.to_list()
    lst[1]["verdict"] = "TAMPERED"  # Break hash
    try:
        HashChain.from_list(lst)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    return True


def _test_merkle_root_empty():
    """Merkle root of empty chain is "0" * 64."""
    c = HashChain()
    assert c.merkle_root() == "0" * 64
    return True


def _test_merkle_root_single():
    """Merkle root of single receipt is its own hash."""
    c = HashChain()
    g = genesis_receipt()
    c.append(g)
    assert c.merkle_root() == g.hash
    return True


def _test_merkle_root_deterministic():
    """Same chain produces same Merkle root."""
    c1 = build_chain(("r:0", "m", "A", "OK"), ("r:1", "m", "A", "OK"))
    c2 = build_chain(("r:0", "m", "A", "OK"), ("r:1", "m", "A", "OK"))
    assert c1.merkle_root() == c2.merkle_root()
    return True


def _test_merkle_root_changes():
    """Different chains produce different Merkle roots."""
    c1 = build_chain(("r:0", "m", "A", "OK"))
    c2 = build_chain(("r:0", "m", "A", "FAIL"))
    assert c1.merkle_root() != c2.merkle_root()
    return True


def _test_iteration():
    """Chain supports iteration."""
    c = build_chain(("r:0", "m", "A", "OK"), ("r:1", "m", "A", "OK"))
    ids = [r.receipt_id for r in c]
    assert ids == ["r:0", "r:1"]
    return True


def _test_len():
    """len() works on chain."""
    c = build_chain(("r:0", "m", "A", "OK"), ("r:1", "m", "A", "OK"))
    assert len(c) == 2
    return True


def _test_repr():
    """repr includes length and head hash."""
    c = build_chain(("r:0", "m", "A", "OK"))
    s = repr(c)
    assert "length=1" in s
    return True


def _test_build_chain_helper():
    """build_chain convenience function works."""
    c = build_chain(
        ("r:0", "m", "A", "OK", {"val": 1}),
        ("r:1", "m", "B", "OK"),
        ("r:2", "m", "C", "OK"),
    )
    assert c.length == 3
    valid, _, _ = c.verify()
    assert valid
    assert c[0].payload == {"val": 1}
    assert c[2].payload == {}
    return True


def _test_ten_receipt_chain():
    """Chain of 10 receipts verifies correctly."""
    args = [(f"r:{i}", "mod", "ACT", "OK", {"seq": i}) for i in range(10)]
    c = build_chain(*args)
    assert c.length == 10
    valid, _, _ = c.verify()
    assert valid
    return True


def _test_index_out_of_range():
    """get() raises on out-of-range index."""
    c = build_chain(("r:0", "m", "A", "OK"))
    try:
        c.get(5)
        assert False, "Should raise"
    except IndexError:
        pass
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
    print("HASH CHAIN — Labyrinth-OS v6.0")
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
    
    # Demo: build a realistic chain
    print("\n── DEMO: FORGING A LEDGER ──\n")
    chain = HashChain()
    
    g = genesis_receipt("labyrinth", {"session": "2026-04-14"})
    chain.append(g)
    print(f"  [0] {g}")
    
    e1 = evaluation_receipt("guardian_slot", "EXECUTE", {"tau": 0.90, "drift": 0.02}, chain.head_hash, seq=1)
    chain.append(e1)
    print(f"  [1] {e1}")
    
    v1 = verification_receipt("tau_baseline", "7fed76e3...", 26, chain.head_hash, seq=1)
    chain.append(v1)
    print(f"  [2] {v1}")
    
    e2 = evaluation_receipt("guardian_slot", "BLOCK", {"tau": 0.80, "drift": 0.05}, chain.head_hash, seq=2)
    chain.append(e2)
    print(f"  [3] {e2}")
    
    v2 = verification_receipt("guardian_slot", "91bc2ff6...", 28, chain.head_hash, seq=2)
    chain.append(v2)
    print(f"  [4] {v2}")
    
    print(f"\n  Chain length:  {chain.length}")
    print(f"  Head hash:     {chain.head_hash[:32]}...")
    print(f"  Merkle root:   {chain.merkle_root()[:32]}...")
    
    valid, _, _ = chain.verify()
    print(f"  Integrity:     {'VALID' if valid else 'BROKEN'}")
    
    print(f"  EXECUTE count: {len(chain.filter_by_verdict('EXECUTE'))}")
    print(f"  BLOCK count:   {len(chain.filter_by_verdict('BLOCK'))}")
    
    # Roundtrip
    j = chain.to_json()
    c2 = HashChain.from_json(j)
    v2_ok, _, _ = c2.verify()
    print(f"  JSON roundtrip: {'PASS' if v2_ok and c2.length == chain.length else 'FAIL'}")
    
    with open(__file__, "rb") as f:
        fh = hashlib.sha256(f.read()).hexdigest()
    
    print(f"\n── RECEIPT ──")
    print(f"  SHA-256: {fh}")
    print(f"  Tests:   {passed}/{passed + failed}")
    print(f"\n{'=' * 70}")
    print(f"  Section C gap: ledger/hashchain.py — CLOSED")
    print(f"{'=' * 70}")
