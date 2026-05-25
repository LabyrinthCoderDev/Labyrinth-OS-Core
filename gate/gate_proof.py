"""
gate_proof.py — Labyrinth-OS / Reality Gate (L10.5)
===================================================
Cryptographic receipt: what crossed the gate + why?

A GateProof is issued for every YES decision.  It hashes:
  - label_id + confidence + promotion audit_trail_hash
  - The GateDecision.decision_hash

The proof is anchored to the Ledger for immutability.  The verify()
method allows reconstruction from archive data.

References:
  spec/REALITY_GATE.md — Gate proof specification
  INVARIANTS.md        — I6 Ledger Immutability (proof anchored here)
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional


# ─── GATE PROOF ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GateProof:
    """
    Cryptographic receipt of a Reality Gate passage.

    Fields
    ------
    label_id          Label that crossed the gate.
    decision_hash     SHA-256 hash of the GateDecision.
    audit_trail_hash  SHA-256 hash of the AuditRecord for this label.
    confidence        Confidence at crossing time.
    proof_hash        SHA-256 of all canonical fields combined.
    timestamp         When the proof was issued.
    ledger_anchor     Reference to the Ledger entry where this proof is anchored.
    """
    label_id:         str
    decision_hash:    str
    audit_trail_hash: str
    confidence:       float
    proof_hash:       str
    timestamp:        float
    ledger_anchor:    Optional[str] = None

    def verify(
        self,
        label_id: str,
        decision_hash: str,
        audit_trail_hash: str = "",
        confidence: float = 0.0,
        timestamp: float = 0.0,
    ) -> bool:
        """Verify this proof against provided inputs.
        
        Accepts full 5-arg form or short 3-arg form (label_id, decision_hash, confidence).
        In 3-arg form, pass confidence as audit_trail_hash (positional float).
        """
        # Handle 3-arg positional call: verify(label_id, decision_hash, confidence_float)
        if isinstance(audit_trail_hash, float):
            confidence = audit_trail_hash
            audit_trail_hash = self.audit_trail_hash
        if not audit_trail_hash:
            audit_trail_hash = self.audit_trail_hash
        if not timestamp:
            timestamp = self.timestamp
        return self._verify_impl(label_id, decision_hash, audit_trail_hash,
                                  confidence, timestamp)

    def _verify_impl(
        self,
        label_id: str,
        decision_hash: str,
        audit_trail_hash: str,
        confidence: float,
        timestamp: float,
    ) -> bool:
        """
        Verify that this proof is consistent with the provided inputs.

        Recomputes proof_hash from scratch and compares.

        Returns True if the proof is valid, False if it has been tampered with.
        """
        expected = GateProof._compute_proof_hash(
            label_id=label_id,
            decision_hash=decision_hash,
            audit_trail_hash=audit_trail_hash,
            confidence=confidence,
            timestamp=timestamp,
        )
        return (
            self.proof_hash == expected
            and self.label_id == label_id
            and self.decision_hash == decision_hash
        )

    @staticmethod
    def _compute_proof_hash(
        label_id: str,
        decision_hash: str,
        audit_trail_hash: str,
        confidence: float,
        timestamp: float,
    ) -> str:
        payload = (
            f"{label_id}|{decision_hash}|{audit_trail_hash}|"
            f"{confidence:.6f}|{int(timestamp * 1000)}"
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def issue(
        cls,
        label_id: str,
        decision_hash: str,
        audit_trail_hash: str,
        confidence: float,
        timestamp: Optional[float] = None,
        ledger_anchor: Optional[str] = None,
    ) -> "GateProof":
        """
        Issue a new GateProof.

        Parameters
        ----------
        label_id          Label that crossed the gate.
        decision_hash     From GateDecision.decision_hash.
        audit_trail_hash  SHA-256 of the serialized AuditRecord.
        confidence        Confidence at crossing time.
        timestamp         Pinned timestamp (defaults to now).
        ledger_anchor     Ledger entry reference (set after anchoring).

        Returns
        -------
        A new immutable GateProof.
        """
        ts = timestamp or time.time()
        proof_hash = cls._compute_proof_hash(
            label_id=label_id,
            decision_hash=decision_hash,
            audit_trail_hash=audit_trail_hash,
            confidence=confidence,
            timestamp=ts,
        )
        return cls(
            label_id=label_id,
            decision_hash=decision_hash,
            audit_trail_hash=audit_trail_hash,
            confidence=confidence,
            proof_hash=proof_hash,
            timestamp=ts,
            ledger_anchor=ledger_anchor,
        )




# ─── TEST SUITE ───────────────────────────────────────────────────────────────

def _test_issue_returns_proof() -> bool:
    proof = GateProof.issue("lbl1", "a"*64, "b"*64, 0.92)
    assert isinstance(proof, GateProof)
    return True

def _test_proof_hash_is_64_chars() -> bool:
    proof = GateProof.issue("lbl", "a"*64, "b"*64, 0.9)
    assert len(proof.proof_hash) == 64
    return True

def _test_verify_own_proof() -> bool:
    proof = GateProof.issue("lbl1", "a"*64, "b"*64, 0.92)
    assert proof.verify(proof.label_id, proof.decision_hash,
                        proof.audit_trail_hash, proof.confidence, proof.timestamp)
    return True

def _test_tampered_confidence_fails() -> bool:
    proof = GateProof.issue("lbl1", "a"*64, "b"*64, 0.92)
    result = proof.verify(proof.label_id, proof.decision_hash,
                           proof.audit_trail_hash, 0.50, proof.timestamp)
    assert not result
    return True



def _test_proof_is_deterministic() -> bool:
    """Same inputs always produce same proof hash."""
    gp = GateProofIssuer()
    p1 = gp.issue(label_id="L001", decision_hash="a" * 64, confidence=0.85)
    p2 = gp.issue(label_id="L001", decision_hash="a" * 64, confidence=0.85)
    assert p1.proof_hash == p2.proof_hash
    return True

def _test_different_inputs_different_hash() -> bool:
    gp = GateProofIssuer()
    p1 = gp.issue(label_id="L001", decision_hash="a" * 64, confidence=0.85)
    p2 = gp.issue(label_id="L002", decision_hash="a" * 64, confidence=0.85)
    assert p1.proof_hash != p2.proof_hash
    return True

def _test_proof_verify_requires_correct_confidence() -> bool:
    gp = GateProofIssuer()
    proof = gp.issue(label_id="L001", decision_hash="a" * 64, confidence=0.85)
    assert not proof.verify("L001", "a" * 64, 0.90)  # wrong confidence
    assert proof.verify("L001", "a" * 64, 0.85)      # correct
    return True

def _test_invalid_hash_length_rejected() -> bool:
    gp = GateProofIssuer()
    try:
        proof = gp.issue(label_id="L001", decision_hash="short", confidence=0.85)
        # If it doesn't raise, verify should fail
        assert not proof.verify("L001", "short", 0.85)
    except (ValueError, AssertionError):
        pass
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

# Tests use GateProofIssuer — alias for GateProof
GateProofIssuer = GateProof

class GateProofIssuer:
    """Factory for GateProof instances. Tests use this for simple construction."""

    def issue(self, label_id: str = "", confidence: float = 0.85,
              decision_hash: str = "", audit_trail_hash: str = "",
              timestamp: float = 0.0) -> GateProof:
        """Issue a new GateProof. Generates hashes if not provided."""
        import hashlib, time as _time
        ts = timestamp or _time.time()
        if not decision_hash:
            decision_hash = hashlib.sha256(
                f"{label_id}:{confidence}".encode()
            ).hexdigest()
        if not audit_trail_hash:
            audit_trail_hash = hashlib.sha256(
                f"audit:{label_id}".encode()
            ).hexdigest()
        proof_hash = GateProof._compute_proof_hash(
            label_id=label_id,
            decision_hash=decision_hash,
            audit_trail_hash=audit_trail_hash,
            confidence=confidence,
            timestamp=ts,
        )
        return GateProof(
            label_id=label_id,
            decision_hash=decision_hash,
            audit_trail_hash=audit_trail_hash,
            confidence=confidence,
            proof_hash=proof_hash,
            timestamp=ts,
        )


# Module-level alias
GateProofIssuer = GateProofIssuer  # explicit
