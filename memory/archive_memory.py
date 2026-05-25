"""
archive_memory.py — Labyrinth-OS / Lane 1 / L06
================================================
L06 Archive Memory

Immutable versioned store. Every labeled idea enters archive.
Nothing is deleted. Nothing is overwritten. Everything becomes memory.

Archive rules:
  - APPEND ONLY: ideas are never deleted
  - VERSIONED: label changes create new versions, not overwrites
  - COMPLETE: every idea, regardless of label, enters archive
  - INDEXED: ideas are retrievable by id, label, mode, and time range

The archive is not execution storage. It does not feed Lane 2 directly.
It feeds L07 (Deferred Exploration) and L08 (Promotion Protocol).

References:
  ARCHITECTURE.md — L06 Archive Memory
  epistemic_types.py — IdeaNode
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from epistemic_types import EpistemicLabel, IdeaNode, InputMode


# ─── ARCHIVE ENTRY ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ArchiveEntry:
    """
    One immutable entry in the archive.

    version       — monotonically increasing within the same idea_id
    node          — the IdeaNode at time of archiving
    archived_at   — wall clock time of archival
    entry_hash    — SHA-256 of (idea_id + version + content_hash + label)
    """
    idea_id:     str
    version:     int
    node:        IdeaNode
    archived_at: float
    entry_hash:  str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id":     self.idea_id,
            "version":     self.version,
            "label":       self.node.label.value,
            "mode":        self.node.mode.value,
            "archived_at": self.archived_at,
            "entry_hash":  self.entry_hash,
            "content_hash":self.node.content_hash,
        }

    @staticmethod
    def compute_hash(idea_id: str, version: int,
                     content_hash: str, label: EpistemicLabel) -> str:
        payload = f"{idea_id}:{version}:{content_hash}:{label.value}"
        return hashlib.sha256(payload.encode()).hexdigest()


# ─── ARCHIVE MEMORY ───────────────────────────────────────────────────────────

class ArchiveMemory:
    """
    L06: Immutable versioned memory store.

    Append-only. All ideas, all labels, all versions.
    Nothing is deleted. Nothing is overwritten.

    Thread safety: not guaranteed — single-session use.
    Persistent storage: not implemented — in-memory for now.
    (Persistent storage is L17 territory — Ledger/WORM)
    """

    def __init__(self) -> None:
        self._store: Dict[str, List[ArchiveEntry]] = {}   # idea_id → versions
        self._total: int = 0

    def archive(self, node: IdeaNode) -> ArchiveEntry:
        """
        Archive an IdeaNode. Creates a new version entry.
        Always succeeds — archive never rejects.

        Returns the created ArchiveEntry.
        """
        versions = self._store.setdefault(node.idea_id, [])
        version = len(versions)
        entry_hash = ArchiveEntry.compute_hash(
            node.idea_id, version, node.content_hash, node.label
        )
        entry = ArchiveEntry(
            idea_id=node.idea_id,
            version=version,
            node=node,
            archived_at=time.time(),
            entry_hash=entry_hash,
        )
        versions.append(entry)
        self._total += 1
        return entry

    def get_latest(self, idea_id: str) -> Optional[ArchiveEntry]:
        """Get the most recent version of an idea."""
        versions = self._store.get(idea_id, [])
        return versions[-1] if versions else None

    def get_all_versions(self, idea_id: str) -> List[ArchiveEntry]:
        """Get all versions of an idea, oldest first."""
        return list(self._store.get(idea_id, []))

    def get_by_label(self, label: EpistemicLabel) -> List[ArchiveEntry]:
        """Get latest version of all ideas with a given label."""
        results = []
        for versions in self._store.values():
            if versions and versions[-1].node.label == label:
                results.append(versions[-1])
        return results

    def get_by_mode(self, mode: InputMode) -> List[ArchiveEntry]:
        """Get latest version of all ideas with a given mode."""
        results = []
        for versions in self._store.values():
            if versions and versions[-1].node.mode == mode:
                results.append(versions[-1])
        return results

    def all_latest(self) -> Iterator[ArchiveEntry]:
        """Iterate over the latest version of every archived idea."""
        for versions in self._store.values():
            if versions:
                yield versions[-1]

    @property
    def total_entries(self) -> int:
        """Total entries across all ideas and all versions."""
        return self._total

    @property
    def unique_ideas(self) -> int:
        """Number of unique idea_ids in archive."""
        return len(self._store)

    def summary(self) -> Dict[str, Any]:
        label_counts = {}
        for entry in self.all_latest():
            lv = entry.node.label.value
            label_counts[lv] = label_counts.get(lv, 0) + 1
        return {
            "unique_ideas":  self.unique_ideas,
            "total_entries": self.total_entries,
            "by_label":      label_counts,
        }


# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _make_node(idea_id="n1", label=EpistemicLabel.UNKNOWN):
    from epistemic_types import InputMode
    return IdeaNode(idea_id=idea_id, content=f"content of {idea_id}",
                    label=label, mode=InputMode.ANALYTICAL)

def _test_archive_returns_entry() -> bool:
    """archive() returns an ArchiveEntry with correct fields."""
    memory = ArchiveMemory()
    node = _make_node()
    entry = memory.archive(node)
    assert entry.idea_id == "n1"
    assert entry.version == 0
    assert len(entry.entry_hash) == 64
    return True

def _test_archive_never_rejects() -> bool:
    """archive() accepts any IdeaNode regardless of label."""
    memory = ArchiveMemory()
    for label in EpistemicLabel:
        node = _make_node(f"id_{label.value}", label)
        entry = memory.archive(node)
        assert entry is not None
    return True

def _test_versions_increment() -> bool:
    """Same idea archived twice → two versions."""
    memory = ArchiveMemory()
    from epistemic_types import InputMode
    from dataclasses import replace
    node = _make_node()
    e0 = memory.archive(node)
    node2 = replace(node, label=EpistemicLabel.SPECULATIVE)
    e1 = memory.archive(node2)
    assert e0.version == 0
    assert e1.version == 1
    assert memory.get_latest("n1").version == 1
    return True

def _test_get_latest_returns_newest() -> bool:
    """get_latest() returns most recent version."""
    memory = ArchiveMemory()
    from dataclasses import replace
    node = _make_node()
    memory.archive(node)
    node2 = replace(node, label=EpistemicLabel.DEFERRED)
    memory.archive(node2)
    latest = memory.get_latest("n1")
    assert latest.node.label == EpistemicLabel.DEFERRED
    return True

def _test_get_by_label() -> bool:
    """get_by_label() returns only matching ideas."""
    memory = ArchiveMemory()
    memory.archive(_make_node("a", EpistemicLabel.TRUTH))
    memory.archive(_make_node("b", EpistemicLabel.SPECULATIVE))
    memory.archive(_make_node("c", EpistemicLabel.TRUTH))
    truths = memory.get_by_label(EpistemicLabel.TRUTH)
    assert len(truths) == 2
    assert all(e.node.label == EpistemicLabel.TRUTH for e in truths)
    return True

def _test_get_all_versions() -> bool:
    """get_all_versions() returns all historical versions."""
    memory = ArchiveMemory()
    from dataclasses import replace
    node = _make_node()
    for label in [EpistemicLabel.UNKNOWN, EpistemicLabel.SPECULATIVE,
                  EpistemicLabel.DEFERRED]:
        memory.archive(replace(node, label=label))
    versions = memory.get_all_versions("n1")
    assert len(versions) == 3
    return True

def _test_nothing_deleted() -> bool:
    """Archiving a new version doesn't remove old ones."""
    memory = ArchiveMemory()
    from dataclasses import replace
    node = _make_node()
    memory.archive(node)
    old_hash = memory.get_all_versions("n1")[0].entry_hash
    node2 = replace(node, label=EpistemicLabel.SPECULATIVE)
    memory.archive(node2)
    all_versions = memory.get_all_versions("n1")
    assert len(all_versions) == 2
    assert all_versions[0].entry_hash == old_hash  # original preserved
    return True

def _test_summary_counts_correct() -> bool:
    """summary() returns correct unique_ideas and label counts."""
    memory = ArchiveMemory()
    memory.archive(_make_node("x", EpistemicLabel.TRUTH))
    memory.archive(_make_node("y", EpistemicLabel.SPECULATIVE))
    memory.archive(_make_node("z", EpistemicLabel.DEFERRED))
    s = memory.summary()
    assert s["unique_ideas"] == 3
    assert s["by_label"].get("TRUTH") == 1
    return True

def _test_entry_hash_stable() -> bool:
    """Same inputs → same entry_hash every time."""
    h1 = ArchiveEntry.compute_hash("id", 0, "abc", EpistemicLabel.TRUTH)
    h2 = ArchiveEntry.compute_hash("id", 0, "abc", EpistemicLabel.TRUTH)
    assert h1 == h2 and len(h1) == 64
    return True

def _test_to_dict_serializable() -> bool:
    """ArchiveEntry.to_dict() is JSON-serializable."""
    memory = ArchiveMemory()
    entry = memory.archive(_make_node())
    json.dumps(entry.to_dict())
    return True


def run_tests() -> tuple:
    tests = sorted(
        [(name, obj) for name, obj in globals().items()
         if name.startswith("_test_") and callable(obj)],
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
    import hashlib as _hl
    print("=" * 70)
    print("ARCHIVE MEMORY — Labyrinth-OS / Lane 1 / L06")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        raise SystemExit(1)
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}\n  Tests: {passed}/{passed+failed}")
    print(f"\n{'='*70}\n  ARCHIVE MEMORY — COMPLETE\n{'='*70}")
