"""
memory_store.py — Labyrinth-OS / Epistemic Archive Layer (L5.5)
================================================================
Append-only epistemic memory store.

Like the Ledger (L13) but for epistemics.  Every sealed label, promotion
decision, anomaly, and outcome is appended here.  No record may be deleted
or modified; the SHA-256 chain makes tampering detectable.

Invariant enforced:
  I12 — Archive Integrity: append-only epistemic record.

References:
  ARCHITECTURE.md  — L5.5 Archive memory
  spec/ARCHIVE.md  — Formal archive specification
  INVARIANTS.md    — I12 Archive integrity
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum, unique
from typing import Callable, Iterable, List, Optional


# ─── ENTRY TYPE ───────────────────────────────────────────────────────────────

@unique
class EntryType(str, Enum):
    LABEL      = "LABEL"       # sealed LabelRecord
    PROMOTION  = "PROMOTION"   # promotion decision
    REJECTION  = "REJECTION"   # Reality Gate rejection
    ANOMALY    = "ANOMALY"     # observability anomaly
    OUTCOME    = "OUTCOME"     # real-world outcome of a promoted label


# ─── ARCHIVE ENTRY ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArchiveEntry:
    """
    One immutable record in the append-only archive.

    Fields
    ------
    entry_id      Sequential monotonic identifier (1, 2, 3 …)
    entry_type    EntryType
    label_id      Label this record is associated with (may be None for ANOMALY)
    payload       Serializable dict carrying entry-specific data
    timestamp     Unix epoch float
    prev_hash     SHA-256 of the previous entry (genesis = "0" * 64)
    entry_hash    SHA-256 of this entry's canonical fields
    """
    entry_id:   int
    entry_type: EntryType
    label_id:   Optional[str]
    payload:    dict
    timestamp:  float
    prev_hash:  str
    entry_hash: str

    @staticmethod
    def _compute_hash(
        entry_id: int,
        entry_type: str,
        label_id: Optional[str],
        payload: dict,
        timestamp: float,
        prev_hash: str,
    ) -> str:
        canonical = json.dumps(
            {
                "entry_id": entry_id,
                "entry_type": entry_type,
                "label_id": label_id,
                "payload": payload,
                "timestamp": int(timestamp * 1000),  # ms precision
                "prev_hash": prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()


# ─── MEMORY STORE ─────────────────────────────────────────────────────────────

class MemoryStore:
    """
    Append-only SHA-256-chained epistemic memory store.

    Thread-safe via an internal lock.

    Usage::

        store = MemoryStore()
        entry = store.append(
            entry_type=EntryType.LABEL,
            label_id="lbl-001",
            payload={"category": "VALID", "confidence": 0.92},
        )
        print(store.verify())   # True
    """

    GENESIS_HASH: str = "0" * 64

    def __init__(self) -> None:
        self._entries: List[ArchiveEntry] = []
        self._sealed: bool = False  # seal() freezes the archive
        self._lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def append(
        self,
        entry_type: EntryType,
        label_id: Optional[str],
        payload: dict,
        timestamp: Optional[float] = None,
    ) -> ArchiveEntry:
        """
        Append a new entry to the archive.

        Parameters
        ----------
        entry_type  Type of record being archived.
        label_id    Associated label (None for ANOMALY entries).
        payload     Arbitrary serializable dict for entry-specific data.
        timestamp   Unix epoch float (defaults to now).

        Returns
        -------
        The sealed ArchiveEntry.
        """
        if self._sealed:
            raise RuntimeError("ArchiveMemory is sealed — no further appends allowed")
        with self._lock:
            ts = timestamp or time.time()
            entry_id = len(self._entries) + 1
            prev_hash = (
                self._entries[-1].entry_hash
                if self._entries
                else self.GENESIS_HASH
            )
            entry_hash = ArchiveEntry._compute_hash(
                entry_id=entry_id,
                entry_type=entry_type.value,
                label_id=label_id,
                payload=payload,
                timestamp=ts,
                prev_hash=prev_hash,
            )
            entry = ArchiveEntry(
                entry_id=entry_id,
                entry_type=entry_type,
                label_id=label_id,
                payload=payload,
                timestamp=ts,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            self._entries.append(entry)
            return entry

    def verify(self) -> bool:
        """
        Verify the integrity of the entire chain.

        Recomputes each entry_hash from scratch and checks prev_hash linkage.
        Returns True if the chain is intact, False if any tampering is detected.
        """
        with self._lock:
            prev = self.GENESIS_HASH
            for entry in self._entries:
                if entry.prev_hash != prev:
                    return False
                expected = ArchiveEntry._compute_hash(
                    entry_id=entry.entry_id,
                    entry_type=entry.entry_type.value,
                    label_id=entry.label_id,
                    payload=entry.payload,
                    timestamp=entry.timestamp,
                    prev_hash=entry.prev_hash,
                )
                if entry.entry_hash != expected:
                    return False
                prev = entry.entry_hash
            return True

    def query(
        self,
        *,
        entry_type: Optional[EntryType] = None,
        label_id: Optional[str] = None,
        since: Optional[float] = None,
        limit: Optional[int] = None,
        predicate: Optional[Callable[[ArchiveEntry], bool]] = None,
    ) -> List[ArchiveEntry]:
        """
        Query entries with optional filters.

        All filters are ANDed together.  Results are chronologically ordered.
        """
        with self._lock:
            results = list(self._entries)

        if entry_type is not None:
            results = [e for e in results if e.entry_type == entry_type]
        if label_id is not None:
            results = [e for e in results if e.label_id == label_id]
        if since is not None:
            results = [e for e in results if e.timestamp >= since]
        if predicate is not None:
            results = [e for e in results if predicate(e)]
        if limit is not None:
            results = results[-limit:]
        return results

    def latest_entry(self) -> Optional[ArchiveEntry]:
        """Return the most recently appended entry."""
        with self._lock:
            return self._entries[-1] if self._entries else None

    def count(self) -> int:
        """Return the total number of archived entries."""
        with self._lock:
            return len(self._entries)

    def seal(self) -> None:
        """Freeze the archive. No further appends allowed after this.

        PROTOTYPE NOTE: This is advisory in Python — language-level enforcement
        is not possible without Rust. In production, the Rust ledger-chronicle
        crate provides true WORM guarantees. Here we raise on any append after seal.
        """
        self._sealed = True

    @property
    def entries(self) -> tuple:
        """Read-only view of archive entries. Returns tuple — not mutable."""
        return tuple(self._entries)


    def tip_hash(self) -> str:
        """Return the hash of the latest entry (or GENESIS_HASH if empty)."""
        with self._lock:
            return (
                self._entries[-1].entry_hash
                if self._entries
                else self.GENESIS_HASH
            )




# ─── TEST SUITE ───────────────────────────────────────────────────────────────


# ─── FEATURE WEIGHT LEARNER ───────────────────────────────────────────────────
# Adapted from Labyrinth-OS Mini — ported to full system's ArchiveEntry model.

import math
import sqlite3
from collections import defaultdict

_FEATURE_NAMES = ["confidence", "tau_escape", "chi", "drift", "betti_1"]
_MIN_SAMPLES   = 10   # minimum per outcome class before weights deviate from uniform


class _FeatureWeightLearner:
    """
    Learns which sigma-anchor features best discriminate success from failure.
    Weights are used by MemoryStore.find_similar() to improve similarity search.
    Starts at uniform weights; improves as outcome history accumulates.
    """

    def __init__(self) -> None:
        self._weights: list[float] = [1.0 / len(_FEATURE_NAMES)] * len(_FEATURE_NAMES)
        self._success_vecs: list[list[float]] = []
        self._failure_vecs: list[list[float]] = []

    def update(self, vector: list[float], succeeded: bool) -> None:
        if succeeded:
            self._success_vecs.append(vector)
        else:
            self._failure_vecs.append(vector)
        if (len(self._success_vecs) >= _MIN_SAMPLES and
                len(self._failure_vecs) >= _MIN_SAMPLES):
            self._recompute_weights()

    def _recompute_weights(self) -> None:
        n = len(_FEATURE_NAMES)
        raw = []
        for i in range(n):
            s_vals = [v[i] for v in self._success_vecs if i < len(v)]
            f_vals = [v[i] for v in self._failure_vecs if i < len(v)]
            if not s_vals or not f_vals:
                raw.append(0.0)
                continue
            s_mean = sum(s_vals) / len(s_vals)
            f_mean = sum(f_vals) / len(f_vals)
            all_vals = s_vals + f_vals
            variance = sum((x - (sum(all_vals)/len(all_vals)))**2
                           for x in all_vals) / len(all_vals)
            std = math.sqrt(variance) if variance > 0 else 1e-6
            raw.append(abs(s_mean - f_mean) / std)
        total = sum(raw)
        if total > 0:
            self._weights = [r / total for r in raw]
        else:
            self._weights = [1.0 / n] * n

    def weights(self) -> list[float]:
        return list(self._weights)


# ─── SIMILARITY RESULT ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SimilarityResult:
    """One result from MemoryStore.find_similar()."""
    entry_id:      int
    label_id:      Optional[str]
    entry_type:    str
    similarity:    float
    outcome:       Optional[str]   # from payload.get("outcome")
    confidence:    Optional[float] # from payload.get("confidence")


# ─── PERSISTENT MEMORY STORE ─────────────────────────────────────────────────

class PersistentMemoryStore(MemoryStore):
    """
    MemoryStore with SQLite persistence and similarity search.

    Drop-in replacement for MemoryStore. All existing behaviour is preserved.
    Additional capabilities:
      - SQLite index survives restarts (index_path parameter)
      - find_similar(): weighted Euclidean similarity over sigma-anchor features
      - risk_estimate(): pre-flight risk based on historical similar entries
      - Feature weights learned from outcome history (improves over time)

    Usage::

        store = PersistentMemoryStore(index_path="/var/labyrinth/memory_index.db")
        entry = store.append(
            entry_type=EntryType.LABEL,
            label_id="lbl-001",
            payload={"confidence": 0.92, "tau_escape": 0.88, "outcome": "EXECUTED"},
        )
        risk = store.risk_estimate(confidence=0.85, tau_escape=0.80)
        similar = store.find_similar(confidence=0.85, top_k=5)
    """

    def __init__(self, index_path: Optional[str] = None) -> None:
        super().__init__()
        self._index_path = index_path
        self._db: Optional[sqlite3.Connection] = None
        self._learner = _FeatureWeightLearner()
        # Feature index: entry_id → feature vector for similarity search
        self._feature_index: dict[int, list[float]] = {}

        if index_path:
            self._db = self._open_db(index_path)
            if not self._load_from_db():
                pass  # empty DB — will populate as entries arrive

    # ── SQLite persistence ────────────────────────────────────────────────────

    def _open_db(self, path: str) -> sqlite3.Connection:
        db = sqlite3.connect(path, check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS entry_index (
                entry_id   INTEGER PRIMARY KEY,
                label_id   TEXT,
                entry_type TEXT,
                confidence REAL,
                tau_escape REAL,
                chi        REAL,
                drift      REAL,
                betti_1    REAL,
                outcome    TEXT,
                timestamp  REAL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS feature_weights (
                feature TEXT PRIMARY KEY,
                weight  REAL NOT NULL
            )
        """)
        db.commit()
        return db

    def _load_from_db(self) -> bool:
        if not self._db:
            return False
        try:
            cur = self._db.execute("SELECT value FROM meta WHERE key='entry_count'")
            row = cur.fetchone()
            if not row:
                return False
            # Restore feature index
            for row in self._db.execute(
                "SELECT entry_id, label_id, entry_type, confidence, tau_escape, "
                "chi, drift, betti_1, outcome, timestamp FROM entry_index"
            ):
                eid, lid, etype, conf, tau, chi, drift, betti, outcome, ts = row
                vec = [conf or 0.0, tau or 0.0, chi or 0.0, drift or 0.0, betti or 0.0]
                self._feature_index[eid] = vec
            # Restore feature weights
            for row in self._db.execute("SELECT feature, weight FROM feature_weights"):
                fname, w = row
                try:
                    idx = _FEATURE_NAMES.index(fname)
                    self._learner._weights[idx] = w
                except (ValueError, IndexError):
                    pass
            return True
        except Exception:
            return False

    def _save_entry_to_db(self, entry: ArchiveEntry) -> None:
        if not self._db:
            return
        p = entry.payload
        try:
            with self._db:
                self._db.execute(
                    """INSERT OR REPLACE INTO entry_index
                       (entry_id, label_id, entry_type, confidence, tau_escape,
                        chi, drift, betti_1, outcome, timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (entry.entry_id, entry.label_id, entry.entry_type,
                     p.get("confidence"), p.get("tau_escape"),
                     p.get("chi"), p.get("drift"), p.get("betti_1"),
                     p.get("outcome"), entry.timestamp)
                )
                self._db.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('entry_count', ?)",
                    (str(len(self._entries)),)
                )
                for name, w in zip(_FEATURE_NAMES, self._learner.weights()):
                    self._db.execute(
                        "INSERT OR REPLACE INTO feature_weights VALUES (?,?)",
                        (name, w)
                    )
        except Exception:
            pass  # fail-safe: DB write failure must not crash the archive

    # ── Override append to maintain feature index ─────────────────────────────

    def append(self,
               entry_type: EntryType,
               label_id: Optional[str] = None,
               payload: Optional[dict] = None) -> ArchiveEntry:
        entry = super().append(entry_type=entry_type,
                               label_id=label_id, payload=payload)
        p = entry.payload
        vec = [
            float(p.get("confidence", 0.0) or 0.0),
            float(p.get("tau_escape",  0.0) or 0.0),
            float(p.get("chi",         0.0) or 0.0),
            float(p.get("drift",       0.0) or 0.0),
            float(p.get("betti_1",     0.0) or 0.0),
        ]
        with self._lock:
            self._feature_index[entry.entry_id] = vec
            outcome = p.get("outcome")
            if outcome in ("EXECUTED", "PROMOTED"):
                self._learner.update(vec, succeeded=True)
            elif outcome in ("BLOCKED", "REJECTED", "FAILED"):
                self._learner.update(vec, succeeded=False)
        self._save_entry_to_db(entry)
        return entry

    # ── Similarity search ─────────────────────────────────────────────────────

    def find_similar(self,
                     confidence: float,
                     tau_escape: Optional[float] = None,
                     chi:        Optional[float] = None,
                     drift:      Optional[float] = None,
                     betti_1:    Optional[float] = None,
                     top_k:      int = 5) -> list:
        """
        Find historically similar archive entries using weighted Euclidean distance.
        Feature weights are learned from outcome history.
        Falls back to uniform weights until MIN_SAMPLES accumulated.
        Returns list of SimilarityResult sorted by similarity (highest first).
        """
        query = [
            confidence,
            tau_escape if tau_escape is not None else 0.5,
            chi        if chi        is not None else 0.1,
            drift      if drift      is not None else 0.05,
            betti_1    if betti_1    is not None else 0.02,
        ]
        weights = self._learner.weights()

        with self._lock:
            results = []
            for entry in self._entries:
                vec = self._feature_index.get(entry.entry_id)
                if vec is None:
                    continue
                dist = math.sqrt(sum(
                    weights[i] * (query[i] - vec[i]) ** 2
                    for i in range(min(len(query), len(vec)))
                ))
                similarity = 1.0 / (1.0 + dist)
                results.append(SimilarityResult(
                    entry_id=entry.entry_id,
                    label_id=entry.label_id,
                    entry_type=entry.entry_type,
                    similarity=similarity,
                    outcome=entry.payload.get("outcome"),
                    confidence=entry.payload.get("confidence"),
                ))

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:top_k]

    # ── Risk estimation ───────────────────────────────────────────────────────

    def risk_estimate(self,
                      confidence: float,
                      tau_escape: Optional[float] = None,
                      chi:        Optional[float] = None,
                      drift:      Optional[float] = None,
                      betti_1:    Optional[float] = None,
                      top_k:      int = 15) -> dict:
        """
        Pre-flight risk estimation based on historically similar archive entries.
        Improves as history accumulates — more entries = better calibration.

        Returns:
            estimated_success_rate: float | None
            sample_count: int
            recommendation: "proceed" | "caution" | "likely_block" | "no_history"
            top_failure_reason: str | None
            feature_weights: dict
        """
        similar = self.find_similar(
            confidence=confidence, tau_escape=tau_escape,
            chi=chi, drift=drift, betti_1=betti_1, top_k=top_k
        )
        if not similar:
            return {
                "estimated_success_rate": None,
                "sample_count":           0,
                "recommendation":         "no_history",
                "note":                   "No similar entries — cannot estimate risk",
                "feature_weights":        {n: round(w, 3)
                                           for n, w in zip(_FEATURE_NAMES,
                                                           self._learner.weights())},
            }

        weighted_success = sum(
            r.similarity for r in similar
            if r.outcome in ("EXECUTED", "PROMOTED")
        )
        weighted_total = sum(r.similarity for r in similar)
        rate = weighted_success / weighted_total if weighted_total > 0 else 0.0

        failure_reasons = [
            r.outcome for r in similar
            if r.outcome not in ("EXECUTED", "PROMOTED", None)
        ]
        top_failure = None
        if failure_reasons:
            from collections import Counter
            top_failure = Counter(failure_reasons).most_common(1)[0][0]

        if rate >= 0.75:   rec = "proceed"
        elif rate >= 0.45: rec = "caution"
        else:              rec = "likely_block"

        return {
            "estimated_success_rate": round(rate, 3),
            "sample_count":           len(similar),
            "recommendation":         rec,
            "top_failure_reason":     top_failure,
            "feature_weights": {n: round(w, 3)
                                for n, w in zip(_FEATURE_NAMES,
                                                self._learner.weights())},
        }


def _test_store_constructs() -> bool:
    ms = MemoryStore()
    assert ms.count() == 0
    return True

def _test_append_increments_count() -> bool:
    ms = MemoryStore()
    ms.append(entry_type=EntryType.LABEL, label_id="e1", payload={"label":"VALID"})
    assert ms.count() == 1
    return True

def _test_no_delete_method() -> bool:
    ms = MemoryStore()
    assert not hasattr(ms, "delete")
    return True

def _test_verify_chain_after_appends() -> bool:
    ms = MemoryStore()
    for i in range(5):
        ms.append(EntryType.LABEL, f"e{i}", {"i":i})
    assert ms.verify()
    return True

def _test_query_by_entry_type() -> bool:
    ms = MemoryStore()
    ms.append(EntryType.LABEL, "e1", {"a":1})
    ms.append(EntryType.PROMOTION, "e2", {"b":2})
    assert len(ms.query(entry_type=EntryType.LABEL)) == 1
    return True

def _test_tip_hash_changes() -> bool:
    ms = MemoryStore()
    h1 = ms.tip_hash()
    ms.append(EntryType.LABEL, "e1", {"x":1})
    h2 = ms.tip_hash()
    assert h1 != h2
    return True



def run_tests() -> tuple:
    tests = sorted([(n,o) for n,o in globals().items()
                    if n.startswith("_test_") and callable(o)], key=lambda x:x[0])
    passed, failed, results = 0, 0, []
    for name, fn in tests:
        try:
            fn(); passed += 1; results.append((name,"PASS",None))
        except Exception as e:
            failed += 1; results.append((name,"FAIL",str(e)))
    return passed, failed, results