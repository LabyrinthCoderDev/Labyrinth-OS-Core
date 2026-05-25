"""
chunk_store.py — Labyrinth-OS / Epistemic / Archive
=====================================================
Lossless Compressed Archive with Hot Index

Purpose:
  Store large knowledge chunks (conversations, research notes, source dumps,
  failed experiment logs) in compressed form while keeping a fast uncompressed
  index for agent lookup.

Rules:
  - Compression is lossless (gzip/zstd). No semantic compression here.
  - Every chunk verified by SHA-256 after decompression.
  - Agents search hot_index.json first — never decompress everything.
  - Retrieve only the exact chunk needed by chunk_id.
  - Hash mismatch fails closed (raises, never returns corrupted data).

What belongs here:
  - Long conversation dumps
  - Research notes and external references
  - Failed experiment logs
  - Cold knowledge that is rarely accessed
  - Semantic summaries of external material

What does NOT belong here:
  - Ledger chain entries (those go in execution/ledger/)
  - Replay proof artifacts
  - Gate decisions
  - ACP-1 evidence
  - Anything needed during live execution

Separation rule:
  Compression may preserve memory.
  It may not decide truth.
  Truth still requires labeling → promotion → reality gate.

Directory structure created:
  {root}/
    hot_index.json     ← fast lookup: topic, tags, hash, pointer
    chunks/            ← compressed chunk files (one per chunk)
    summaries/         ← optional semantic summaries (plain text)
    raw/               ← optional uncompressed originals

References:
  ARCHITECTURE.md          — epistemic archive layer
  archive/KNOWLEDGE_SEEDS.md — what gets archived
  epistemic/archive/memory_store.py — immutable entry store
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Try zstd first, fall back to gzip
try:
    import zstd as _zstd  # type: ignore
    _HAS_ZSTD = True
except ImportError:
    _HAS_ZSTD = False


# ── COMPRESSION LAYER ─────────────────────────────────────────────────────────

def _compress(data: bytes) -> bytes:
    if _HAS_ZSTD:
        return _zstd.compress(data, 9)
    return gzip.compress(data, compresslevel=9)

def _decompress(data: bytes) -> bytes:
    if _HAS_ZSTD:
        try:
            return _zstd.decompress(data)
        except Exception:
            pass  # fall through to gzip
    return gzip.decompress(data)

def _ext() -> str:
    return ".zst" if _HAS_ZSTD else ".gz"


# ── DATA TYPES ────────────────────────────────────────────────────────────────

@dataclass
class ChunkMeta:
    """Index entry for one chunk. Lives uncompressed in hot_index.json."""
    chunk_id:         str      # SHA-256 of raw content
    topic:            str      # human-readable topic
    tags:             List[str]
    source:           str      # where this came from
    raw_bytes:        int      # uncompressed size
    compressed_bytes: int      # on-disk size
    compression:      str      # "gzip" or "zstd"
    created_at:       float    # Unix timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id":         self.chunk_id,
            "topic":            self.topic,
            "tags":             self.tags,
            "source":           self.source,
            "raw_bytes":        self.raw_bytes,
            "compressed_bytes": self.compressed_bytes,
            "compression":      self.compression,
            "created_at":       self.created_at,
            "compression_ratio": round(
                1 - self.compressed_bytes / max(self.raw_bytes, 1), 3
            ),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChunkMeta":
        return cls(
            chunk_id=d["chunk_id"],
            topic=d["topic"],
            tags=d.get("tags", []),
            source=d.get("source", ""),
            raw_bytes=d["raw_bytes"],
            compressed_bytes=d["compressed_bytes"],
            compression=d.get("compression", "gzip"),
            created_at=d.get("created_at", 0.0),
        )


@dataclass
class RetrieveResult:
    """Result of a chunk retrieval. Always includes hash verification status."""
    chunk_id:   str
    topic:      str
    text:       str
    verified:   bool
    meta:       ChunkMeta


# ── CHUNK STORE ───────────────────────────────────────────────────────────────

class ChunkStore:
    """
    Lossless compressed knowledge archive with fast indexed retrieval.

    Usage:
        store = ChunkStore("archive")
        cid = store.add_chunk("A010 replay notes", text, tags=["a010","replay"])
        results = store.search_index("replay")
        doc = store.retrieve(results[0]["chunk_id"])
        print(doc.text)
    """

    def __init__(self, root: str = "archive") -> None:
        self.root       = Path(root)
        self.chunks_dir = self.root / "chunks"
        self.summaries_dir = self.root / "summaries"
        self.raw_dir    = self.root / "raw"
        self.index_path = self.root / "hot_index.json"

        for d in [self.chunks_dir, self.summaries_dir, self.raw_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ── INDEX ─────────────────────────────────────────────────────────────────

    def _load_index(self) -> Dict[str, Dict]:
        if not self.index_path.exists():
            return {}
        with open(self.index_path) as f:
            return json.load(f)

    def _save_index(self, idx: Dict[str, Dict]) -> None:
        with open(self.index_path, 'w') as f:
            json.dump(idx, f, indent=2, sort_keys=True)

    # ── WRITE ─────────────────────────────────────────────────────────────────

    def add_chunk(
        self,
        topic: str,
        text: str,
        tags: Optional[List[str]] = None,
        source: str = "",
        save_raw: bool = False,
    ) -> str:
        """
        Compress and store a text chunk. Returns chunk_id (SHA-256 of raw).
        Idempotent: same content → same chunk_id, existing entry updated in place.
        """
        raw = text.encode("utf-8")
        chunk_id = hashlib.sha256(raw).hexdigest()

        compressed = _compress(raw)
        chunk_path = self.chunks_dir / f"{chunk_id}{_ext()}"
        chunk_path.write_bytes(compressed)

        if save_raw:
            (self.raw_dir / f"{chunk_id}.txt").write_bytes(raw)

        meta = ChunkMeta(
            chunk_id=chunk_id,
            topic=topic,
            tags=tags or [],
            source=source,
            raw_bytes=len(raw),
            compressed_bytes=len(compressed),
            compression="zstd" if _HAS_ZSTD else "gzip",
            created_at=time.time(),
        )

        idx = self._load_index()
        idx[chunk_id] = meta.to_dict()
        self._save_index(idx)

        return chunk_id

    def add_summary(self, chunk_id: str, summary: str) -> None:
        """Add a plain-text semantic summary for an existing chunk."""
        (self.summaries_dir / f"{chunk_id}.txt").write_text(summary, encoding="utf-8")

    # ── READ ──────────────────────────────────────────────────────────────────

    def search_index(self, query: str, tag: Optional[str] = None) -> List[Dict]:
        """
        Search hot_index.json by topic or tag. Never decompresses chunks.
        Returns list of matching index entries with chunk_id pointers.
        """
        q = query.lower().strip()
        results = []
        for entry in self._load_index().values():
            topic_match    = q and q in entry["topic"].lower()
            tag_match      = tag and tag.lower() in [t.lower() for t in entry.get("tags", [])]
            query_in_tags  = q and any(q in t.lower() for t in entry.get("tags", []))
            source_match   = q and q in entry.get("source","").lower()
            if topic_match or tag_match or query_in_tags or source_match:
                results.append(entry)
        return sorted(results, key=lambda e: e["created_at"], reverse=True)

    def retrieve(self, chunk_id: str) -> RetrieveResult:
        """
        Retrieve and decompress a chunk. Verifies SHA-256 after decompression.
        Raises ValueError on hash mismatch (fail closed — never return corrupted data).
        """
        idx = self._load_index()
        if chunk_id not in idx:
            raise KeyError(f"Chunk not found: {chunk_id}")

        meta_dict = idx[chunk_id]
        chunk_path = self.chunks_dir / f"{chunk_id}{_ext()}"

        if not chunk_path.exists():
            # Try the other extension (in case compression changed)
            for ext in [".gz", ".zst"]:
                alt = self.chunks_dir / f"{chunk_id}{ext}"
                if alt.exists():
                    chunk_path = alt
                    break
            else:
                raise FileNotFoundError(f"Chunk file missing: {chunk_id}")

        compressed = chunk_path.read_bytes()
        raw = _decompress(compressed)

        # Hash verification — fail closed
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != chunk_id:
            raise ValueError(
                f"HASH MISMATCH: chunk {chunk_id[:16]}... is corrupted. "
                f"Got {actual_hash[:16]}... Expected {chunk_id[:16]}... "
                f"Do not use this data."
            )

        meta = ChunkMeta.from_dict(meta_dict)
        return RetrieveResult(
            chunk_id=chunk_id,
            topic=meta.topic,
            text=raw.decode("utf-8"),
            verified=True,
            meta=meta,
        )

    def get_summary(self, chunk_id: str) -> Optional[str]:
        """Return semantic summary if one exists. None otherwise."""
        path = self.summaries_dir / f"{chunk_id}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    # ── STATS ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        idx = self._load_index()
        total_raw = sum(e["raw_bytes"] for e in idx.values())
        total_comp = sum(e["compressed_bytes"] for e in idx.values())
        return {
            "chunks":           len(idx),
            "total_raw_kb":     round(total_raw / 1024, 1),
            "total_comp_kb":    round(total_comp / 1024, 1),
            "compression_ratio": round(max(0.0, 1 - total_comp / max(total_raw, 1)), 3),
            "compression":      "zstd" if _HAS_ZSTD else "gzip",
            "index_path":       str(self.index_path),
        }

    def all_chunks(self) -> List[Dict]:
        return list(self._load_index().values())


# ── TEST SUITE ────────────────────────────────────────────────────────────────

def _test_store_and_retrieve() -> bool:
    """Store a chunk, retrieve it, verify content matches exactly."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        text = "This is a test chunk. " * 50
        cid = cs.add_chunk("test topic", text, tags=["test"])
        result = cs.retrieve(cid)
        assert result.text == text
        assert result.verified
        assert result.chunk_id == cid
    return True

def _test_hash_mismatch_fails_closed() -> bool:
    """Tampered chunk raises ValueError — never returns corrupted data."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        cid = cs.add_chunk("tamper test", "original content here yes", tags=[])
        # Tamper with the compressed file
        chunk_path = list((cs.chunks_dir).glob(f"{cid}*"))[0]
        chunk_path.write_bytes(gzip.compress(b"tampered content here!!!"))
        try:
            cs.retrieve(cid)
            raise AssertionError("Should raise ValueError")
        except ValueError as e:
            assert "HASH MISMATCH" in str(e)
    return True

def _test_search_by_topic() -> bool:
    """Search finds matching chunks without decompressing."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        cs.add_chunk("A010 replay session notes", "content A", tags=["a010"])
        cs.add_chunk("Architecture review", "content B", tags=["arch"])
        cs.add_chunk("A010 failure analysis", "content C", tags=["a010","failure"])
        results = cs.search_index("A010")
        assert len(results) == 2
        for r in results:
            assert "a010" in r["topic"].lower() or "a010" in [t.lower() for t in r["tags"]]
    return True

def _test_search_by_tag() -> bool:
    """Search by tag finds correct entries."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        cs.add_chunk("topic 1", "x", tags=["rust", "wasm"])
        cs.add_chunk("topic 2", "y", tags=["python"])
        results = cs.search_index("", tag="rust")
        assert len(results) == 1
        assert results[0]["topic"] == "topic 1"
    return True

def _test_idempotent_same_content() -> bool:
    """Same content → same chunk_id. Index updated, not duplicated."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        text = "identical content stored twice"
        cid1 = cs.add_chunk("first", text)
        cid2 = cs.add_chunk("second", text)
        assert cid1 == cid2
        assert len(cs.all_chunks()) == 1  # not duplicated
    return True

def _test_compression_reduces_size() -> bool:
    """Compressed chunk is smaller than raw."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        text = "compress this " * 500  # repetitive = compresses well
        cid = cs.add_chunk("compression test", text)
        idx = cs.all_chunks()
        entry = next(e for e in idx if e["chunk_id"] == cid)
        assert entry["compressed_bytes"] < entry["raw_bytes"]
    return True

def _test_stats_accurate() -> bool:
    """Stats reflect actual stored data."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        cs.add_chunk("one", "first chunk content here yes")
        cs.add_chunk("two", "second chunk content here yes")
        s = cs.stats()
        assert s["chunks"] == 2
        assert s["total_raw_kb"] > 0
        assert 0.0 <= s["compression_ratio"] <= 1.0
    return True

def _test_summary_stored_and_retrieved() -> bool:
    """Semantic summaries can be added and retrieved separately."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        cid = cs.add_chunk("long doc", "full content " * 100)
        cs.add_summary(cid, "This is the short semantic summary.")
        summary = cs.get_summary(cid)
        assert summary == "This is the short semantic summary."
        assert cs.get_summary("nonexistent") is None
    return True

def _test_missing_chunk_raises_key_error() -> bool:
    """Retrieving nonexistent chunk_id raises KeyError."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cs = ChunkStore(tmp)
        try:
            cs.retrieve("a" * 64)
            raise AssertionError("Should raise KeyError")
        except KeyError:
            pass
    return True

def _test_archive_does_not_import_ledger() -> bool:
    """chunk_store must not import from execution/ledger or CGIR."""
    import ast
    with open(__file__) as f:
        src = f.read()
    forbidden = ["cgir", "ledger", "guardian", "cesk", "gate"]
    imports = [n.name if hasattr(n,'name') else getattr(n,'module','')
               for n in ast.walk(ast.parse(src))
               if isinstance(n, (ast.Import, ast.ImportFrom))]
    for imp in imports:
        for bad in forbidden:
            if bad in str(imp).lower():
                raise AssertionError(f"Forbidden import: {imp} contains '{bad}'")
    return True


def run_tests() -> tuple:
    tests = sorted(
        [(n, o) for n, o in globals().items()
         if n.startswith("_test_") and callable(o)],
        key=lambda x: x[0],
    )
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
    print("CHUNK STORE — Labyrinth-OS / Epistemic Archive")
    print("Lossless compression. Hash verification. Fast indexed retrieval.")
    print("Compression may preserve memory. It may not decide truth.")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed")
    print(f"  Compression: {'zstd' if _HAS_ZSTD else 'gzip (zstd not installed)'}")
    if failed:
        raise SystemExit(1)
    import hashlib as _hl
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}")
    print(f"\n{'='*70}\n  CHUNK STORE — COMPLETE\n{'='*70}")
