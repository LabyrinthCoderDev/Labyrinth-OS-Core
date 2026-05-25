"""
council_resolver.py — Labyrinth-OS / Epistemic Layer v2
========================================================
Council Resolver — Watcher-A + Watcher-B → Single SignalNode

ROLE: LABELING AUTHORITY ONLY.

Council labels signal trust. Council does NOT promote.
Promotion is a separate gate (promotion_protocol.py / promotion_rules.py).

The distinction is structural and enforced:
  - Council emits SignalNode with emitted_by="COUNCIL"
  - That signal is labeled (trusted/untrusted/uncertain)
  - The signal then enters CGIR for structuring
  - Promotion of ideas happens in Lane 1 (L08) — entirely separate

Council CANNOT:
  - promote a SPECULATIVE idea to TRUTH
  - authorize crossing the Reality Gate
  - bypass promotion_protocol

Council CAN:
  - label a sensor signal as trustworthy (high tau, low chi, no drift)
  - label a sensor signal as uncertain (borderline thresholds)
  - label a sensor signal as untrustworthy (CRITICAL/ERROR findings)
  - merge Watcher-A and Watcher-B findings into one authoritative signal

This is the formal definition of council's epistemic role.
Any code that uses council for promotion or gate authorization is a bug.

═══════════════════════════════════════════════════════════
FINDING LEVEL SEMANTICS (authoritative — defined here)
═══════════════════════════════════════════════════════════
  FindingLevel.FAIL  = invariant violation
                       Something required to be true is false.
                       Example: no root→tip path, I1 absent from edge mask.

  FindingLevel.ERROR = system-level inconsistency or corruption
                       Not just wrong — structurally broken or auditor failed.
                       Example: internal watcher exception, hash failure.

  FAIL  → ERROR severity    (invariant broken — graph is invalid)
  ERROR → CRITICAL severity (system may be compromised)
═══════════════════════════════════════════════════════════

Invariant I4: emitted_by="COUNCIL" — hardcoded, non-bypassable.

Changes from v1 (audit fixes):
  1. FAIL vs ERROR semantics defined centrally (here)
  2. Categories are machine-meaningful codes, not human labels
  3. Empty findings → confidence 0.0 (fail closed, not 0.5)
  4. escalation_code added alongside escalation string
  5. determinism_hash on CouncilResult (SHA-256, for replay/proof)
  6. escalation string always contains escalation_code (machine+human)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from cgir_types import NodeType, Severity, SignalNode, TimeRange
from cgir_determinism import stable_hash
from watcher_a import WatcherReport, FindingLevel


# ─── ESCALATION CODES ─────────────────────────────────────────────────────────

class EscalationCode:
    NOMINAL              = "NOMINAL"
    SINGLE_WATCHER_WARN  = "SINGLE_WATCHER_WARN"
    DUAL_WATCHER_WARN    = "DUAL_WATCHER_WARN"
    INVARIANT_BREACH     = "INVARIANT_BREACH"
    CONSISTENCY_FAILURE  = "CONSISTENCY_FAILURE"
    SENSOR_ESCALATION    = "SENSOR_ESCALATION"
    MISSING_WATCHER      = "MISSING_WATCHER"
    SPLIT_BRAIN          = "SPLIT_BRAIN"


# ─── COUNCIL RESULT ───────────────────────────────────────────────────────────

@dataclass
class CouncilResult:
    signal:           SignalNode
    watcher_a:        WatcherReport
    watcher_b:        WatcherReport
    escalation_code:  str
    escalation:       str
    determinism_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.determinism_hash:
            # Include time-window binding so two signals with same
            # severity/category but different logical_time or valid_for
            # produce distinct hashes. Required for proof-safe replay.
            vf = None
            if self.signal.valid_for is not None:
                vf = {
                    "start": self.signal.valid_for.start_time,
                    "end":   self.signal.valid_for.end_time,
                }
            payload = json.dumps({
                "id":             self.signal.id,
                "logical_time":   self.signal.logical_time,
                "severity":       self.signal.severity.value,
                "confidence":     round(self.signal.confidence, 10),
                "category":       self.signal.category,
                "source":         self.signal.source,
                "emitted_by":     self.signal.emitted_by,
                "escalation_code":self.escalation_code,
                "valid_for":      vf,
            }, sort_keys=True, separators=(",", ":"))
            self.determinism_hash = hashlib.sha256(
                payload.encode("utf-8")
            ).hexdigest()


# ─── COUNCIL RESOLVER ─────────────────────────────────────────────────────────

class CouncilResolver:

    def resolve(
        self,
        report_a: Optional[WatcherReport],
        report_b: Optional[WatcherReport],
        signal_id: str,
        logical_time: int,
        valid_for: Optional[TimeRange] = None,
        sensor_severity: Optional[Severity] = None,
        sensor_confidence: Optional[float] = None,
    ) -> CouncilResult:

        # Null guard
        if report_a is None or report_b is None:
            missing = "WATCHER_A" if report_a is None else "WATCHER_B"
            return self._make(signal_id, logical_time, valid_for,
                Severity.CRITICAL, 0.0, "MISSING_WATCHER",
                EscalationCode.MISSING_WATCHER,
                f"CRITICAL [{EscalationCode.MISSING_WATCHER}]: {missing} absent — fail closed",
                report_a or self._null_report("WATCHER_A"),
                report_b or self._null_report("WATCHER_B"))

        # Split-brain guard
        if report_a.graph_hash != report_b.graph_hash:
            return self._make(signal_id, logical_time, valid_for,
                Severity.CRITICAL, 0.0, "SPLIT_BRAIN",
                EscalationCode.SPLIT_BRAIN,
                f"CRITICAL [{EscalationCode.SPLIT_BRAIN}]: hash mismatch "
                f"A={report_a.graph_hash[:12]}… B={report_b.graph_hash[:12]}…",
                report_a, report_b)

        sev, code, esc = self._resolve_severity(report_a, report_b, sensor_severity)
        conf = self._synthesize_confidence(report_a, report_b, sensor_confidence)
        cat  = self._derive_category(report_a, report_b, sev, code)
        return self._make(signal_id, logical_time, valid_for, sev, conf, cat, code, esc, report_a, report_b)

    def _resolve_severity(self, a, b, sensor_severity):
        a_errors = any(f.level == FindingLevel.ERROR for f in a.findings)
        b_errors = any(f.level == FindingLevel.ERROR for f in b.findings)
        a_fails  = any(f.level == FindingLevel.FAIL  for f in a.findings)
        b_fails  = any(f.level == FindingLevel.FAIL  for f in b.findings)
        a_warns  = any(f.level == FindingLevel.WARN  for f in a.findings)
        b_warns  = any(f.level == FindingLevel.WARN  for f in b.findings)

        if a_errors or b_errors:
            sev, code = Severity.CRITICAL, EscalationCode.CONSISTENCY_FAILURE
            esc = (f"CRITICAL [{code}]: system-level error in watcher "
                   f"(A_err={a_errors}, B_err={b_errors})")
        elif a_fails or b_fails:
            sev, code = Severity.ERROR, EscalationCode.INVARIANT_BREACH
            esc = (f"ERROR [{code}]: invariant violation "
                   f"(A_fail={a_fails}, B_fail={b_fails})")
        elif a_warns and b_warns:
            sev, code = Severity.ERROR, EscalationCode.DUAL_WATCHER_WARN
            esc = f"ERROR [{code}]: both watchers WARN — agreement amplifies to ERROR"
        elif a_warns or b_warns:
            sev, code = Severity.WARNING, EscalationCode.SINGLE_WATCHER_WARN
            esc = (f"WARNING [{code}]: one watcher WARN "
                   f"(A={a_warns}, B={b_warns})")
        else:
            sev, code = Severity.INFO, EscalationCode.NOMINAL
            esc = f"INFO [{code}]: both watchers all-clear"

        # TODO (A011 prerequisite): sensor_severity currently enters Council
        # directly as a raw severity override. Long-term, route sensor evidence
        # through a dedicated SensorWatcher validation step before it reaches
        # Council — treat sensors as a third auditor, not a direct escalation
        # bypass. This makes sensor influence traceable in the watcher reports
        # and auditable in replay. Requires logprob_bridge to be wired (A011).
        SEV_ORDER = [Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL]
        if sensor_severity is not None:
            if SEV_ORDER.index(sensor_severity) > SEV_ORDER.index(sev):
                esc += (f" | escalated by sensor {sev.value}→{sensor_severity.value} "
                        f"[{EscalationCode.SENSOR_ESCALATION}]")
                code = EscalationCode.SENSOR_ESCALATION
                sev  = sensor_severity

        return sev, code, esc

    def _synthesize_confidence(self, a, b, sensor_confidence):
        def wconf(r):
            if not r.findings: return 0.0  # fail closed: no findings ≠ healthy
            ok = sum(1 for f in r.findings if f.level == FindingLevel.OK)
            return ok / len(r.findings)
        wm = (wconf(a) + wconf(b)) / 2.0
        if sensor_confidence is not None:
            return max(0.0, min(1.0, 0.5 * wm + 0.5 * max(0.0, min(1.0, sensor_confidence))))
        return max(0.0, min(1.0, wm))

    def _derive_category(self, a, b, severity, code):
        if code in (EscalationCode.SPLIT_BRAIN, EscalationCode.MISSING_WATCHER,
                    EscalationCode.SENSOR_ESCALATION):
            return code
        if severity == Severity.CRITICAL:
            return "CONSISTENCY_FAILURE"
        if severity == Severity.ERROR:
            if code == EscalationCode.INVARIANT_BREACH:
                return "INVARIANT_BREACH"
            for r in (a, b):
                for f in r.findings:
                    if f.level == FindingLevel.WARN:
                        c = f.check
                        if "TEMPORAL" in c: return "TEMPORAL_DRIFT"
                        if "SIGNAL" in c or "INJECTION" in c: return "SIGNAL_ANOMALY"
                        if "EVASION" in c or "REPLAY" in c: return "ADVERSARIAL_PATTERN"
                        if "INVARIANT" in c: return "INVARIANT_BREACH"
            return "DUAL_WATCHER_WARN"
        if severity == Severity.WARNING:
            for r in (a, b):
                for f in r.findings:
                    if f.level == FindingLevel.WARN:
                        c = f.check
                        if "TEMPORAL" in c: return "TEMPORAL_DRIFT"
                        if "SIGNAL" in c or "INJECTION" in c: return "SIGNAL_ANOMALY"
                        if "EVASION" in c: return "GATE_EVASION"
                        if "REPLAY" in c: return "REPLAY_PATTERN"
                        if "INVARIANT" in c: return "INVARIANT_BREACH"
                        if "CONFIDENCE" in c: return "CONFIDENCE_ANOMALY"
                        if "PATH" in c: return "PATH_FAILURE"
                        return f"WARN_{c}"
        return "NOMINAL"

    def _make(self, signal_id, logical_time, valid_for, severity, confidence,
              category, escalation_code, escalation, report_a, report_b):
        sig = SignalNode(
            id=signal_id, node_type=NodeType.SIGNAL,
            logical_time=logical_time,
            severity=severity,
            confidence=max(0.0, min(1.0, confidence)),
            category=category,
            evidence_refs=[], valid_for=valid_for,
            source="COUNCIL", emitted_by="COUNCIL",  # I4
        )
        return CouncilResult(
            signal=sig, watcher_a=report_a, watcher_b=report_b,
            escalation_code=escalation_code, escalation=escalation,
        )

    def _null_report(self, wid):
        from watcher_a import Finding, FindingLevel
        return WatcherReport(graph_hash="", watcher_id=wid, findings=[
            Finding(check="NULL", level=FindingLevel.ERROR,
                    detail=f"{wid} absent")])


def resolve(report_a, report_b, signal_id, logical_time, valid_for=None,
            sensor_severity=None, sensor_confidence=None):
    return CouncilResolver().resolve(
        report_a, report_b, signal_id, logical_time,
        valid_for, sensor_severity, sensor_confidence)


# ─── TEST HELPERS ─────────────────────────────────────────────────────────────

def _clean_reports(graph=None):
    from watcher_a import WatcherA
    from watcher_b import WatcherB
    from cgir_types import Edge, Node, NodeType
    from cgir_core import CGIRGraph
    if graph is None:
        graph = CGIRGraph()
        graph.add_node(Node(id="proposal_main", node_type=NodeType.STATE, logical_time=0))
        graph.add_node(Node(id="proposal_next", node_type=NodeType.STATE, logical_time=1))
        graph.add_edge(Edge(id="step_0", from_id="proposal_main",
                            to_id="proposal_next", event_type="STEP",
                            invariant_mask=["I1"]))
        graph.set_root("proposal_main"); graph.set_tip("proposal_next")
    return WatcherA().audit(graph), WatcherB().audit(graph), graph


# ─── TESTS ────────────────────────────────────────────────────────────────────

def _test_clean_gives_info_nominal() -> bool:
    ra, rb, _ = _clean_reports()
    r = resolve(ra, rb, "s0", 0)
    assert r.signal.severity == Severity.INFO
    assert r.escalation_code == EscalationCode.NOMINAL
    assert r.signal.category == "NOMINAL"
    assert r.signal.emitted_by == "COUNCIL"
    return True

def _test_i4_always_council() -> bool:
    ra, rb, _ = _clean_reports()
    for sev in [None, Severity.INFO, Severity.WARNING, Severity.CRITICAL]:
        r = resolve(ra, rb, "s_i4", 0, sensor_severity=sev)
        assert r.signal.emitted_by == "COUNCIL"
    return True

def _test_null_a_critical_missing() -> bool:
    _, rb, _ = _clean_reports()
    r = resolve(None, rb, "s_na", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.MISSING_WATCHER
    assert r.signal.confidence == 0.0
    assert r.signal.category == "MISSING_WATCHER"
    return True

def _test_null_b_critical_missing() -> bool:
    ra, _, _ = _clean_reports()
    r = resolve(ra, None, "s_nb", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.MISSING_WATCHER
    return True

def _test_split_brain_critical() -> bool:
    from watcher_a import WatcherReport
    ra, rb, _ = _clean_reports()
    rb_bad = WatcherReport(graph_hash="0"*64, watcher_id="WATCHER_B", findings=rb.findings)
    r = resolve(ra, rb_bad, "s_sb", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.SPLIT_BRAIN
    assert r.signal.category == "SPLIT_BRAIN"
    return True

def _test_error_finding_gives_critical_consistency() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    ra_e = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=ra.findings + [Finding("AUDIT_INTERNAL", FindingLevel.ERROR, "sys err")])
    r = resolve(ra_e, rb, "s_err", 0)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.CONSISTENCY_FAILURE
    assert r.signal.category == "CONSISTENCY_FAILURE"
    return True

def _test_fail_finding_gives_error_invariant() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    ra_f = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=ra.findings + [Finding("ROOT_TIP_PATH", FindingLevel.FAIL, "no path")])
    r = resolve(ra_f, rb, "s_fail", 0)
    assert r.signal.severity == Severity.ERROR
    assert r.escalation_code == EscalationCode.INVARIANT_BREACH
    assert r.signal.category == "INVARIANT_BREACH"
    return True

def _test_dual_warn_error_amplifies() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=[Finding("X", FindingLevel.WARN, "w")])
    rb_w = WatcherReport(graph_hash=rb.graph_hash, watcher_id="WATCHER_B",
        findings=[Finding("Y", FindingLevel.WARN, "w")])
    r = resolve(ra_w, rb_w, "s_dw", 0)
    assert r.signal.severity == Severity.ERROR
    assert r.escalation_code == EscalationCode.DUAL_WATCHER_WARN
    assert "amplifies" in r.escalation
    return True

def _test_single_warn_warning() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=[Finding("X", FindingLevel.WARN, "w")])
    r = resolve(ra_w, rb, "s_sw", 0)
    assert r.signal.severity == Severity.WARNING
    assert r.escalation_code == EscalationCode.SINGLE_WATCHER_WARN
    return True

def _test_sensor_escalates_code() -> bool:
    ra, rb, _ = _clean_reports()
    r = resolve(ra, rb, "s_se", 0, sensor_severity=Severity.CRITICAL, sensor_confidence=0.8)
    assert r.signal.severity == Severity.CRITICAL
    assert r.escalation_code == EscalationCode.SENSOR_ESCALATION
    assert "sensor" in r.escalation
    return True

def _test_sensor_does_not_downgrade() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    ra_f = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=[Finding("T", FindingLevel.FAIL, "fail")])
    r = resolve(ra_f, rb, "s_nd", 0, sensor_severity=Severity.INFO)
    assert r.signal.severity == Severity.ERROR  # watcher wins
    return True

def _test_empty_findings_zero_confidence() -> bool:
    from watcher_a import WatcherReport
    ra, rb, _ = _clean_reports()
    ra_e = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A", findings=[])
    rb_e = WatcherReport(graph_hash=rb.graph_hash, watcher_id="WATCHER_B", findings=[])
    r = resolve(ra_e, rb_e, "s_ec", 0)
    assert r.signal.confidence == 0.0, f"Expected 0.0, got {r.signal.confidence}"
    return True

def _test_determinism_hash_present_stable() -> bool:
    ra, rb, _ = _clean_reports()
    r1 = resolve(ra, rb, "s_det", 0)
    r2 = resolve(ra, rb, "s_det", 0)
    assert len(r1.determinism_hash) == 64
    assert r1.determinism_hash == r2.determinism_hash
    return True

def _test_different_outcomes_different_hashes() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    r_nom = resolve(ra, rb, "s_a", 0)
    ra_e = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=[Finding("X", FindingLevel.ERROR, "err")])
    r_crit = resolve(ra_e, rb, "s_b", 0)
    assert r_nom.determinism_hash != r_crit.determinism_hash
    return True

def _test_escalation_code_in_string() -> bool:
    ra, rb, _ = _clean_reports()
    r = resolve(ra, rb, "s_str", 0)
    assert r.escalation_code in r.escalation
    return True

def _test_category_temporal_drift() -> bool:
    from watcher_a import WatcherReport, Finding, FindingLevel
    ra, rb, _ = _clean_reports()
    ra_w = WatcherReport(graph_hash=ra.graph_hash, watcher_id="WATCHER_A",
        findings=[Finding("TEMPORAL_CONSISTENCY", FindingLevel.WARN, "bwd")])
    r = resolve(ra_w, rb, "s_td", 0)
    assert r.signal.category == "TEMPORAL_DRIFT"
    return True

def _test_category_nominal_clean() -> bool:
    ra, rb, _ = _clean_reports()
    r = resolve(ra, rb, "s_cn", 0)
    assert r.signal.category == "NOMINAL"
    return True

def _test_full_pipeline_integration() -> bool:
    from watcher_a import WatcherA
    from watcher_b import WatcherB
    from cgir_validator import validate
    from cgir_types import Edge, Node, NodeType, TimeRange
    from cgir_core import CGIRGraph

    g = CGIRGraph()
    g.add_node(Node(id="proposal_main", node_type=NodeType.STATE, logical_time=0))
    g.add_node(Node(id="proposal_next", node_type=NodeType.STATE, logical_time=1))
    g.add_edge(Edge(id="step_0", from_id="proposal_main", to_id="proposal_next",
                    event_type="STEP", invariant_mask=["I1"],
                    signal_binding="council_sig_0"))
    g.set_root("proposal_main"); g.set_tip("proposal_next")
    ra = WatcherA().audit(g)
    rb = WatcherB().audit(g)
    council = resolve(ra, rb, "council_sig_0", 0,
                      valid_for=TimeRange(start_time=0, end_time=1))
    g.add_signal(council.signal)
    vr = validate(g)
    assert vr.valid, f"Validation failed: {[e.to_dict() for e in vr.errors]}"
    assert council.escalation_code == EscalationCode.NOMINAL
    assert len(council.determinism_hash) == 64
    return True



def _test_different_logical_time_different_hash() -> bool:
    """Two identical signals at different logical_time produce different hashes."""
    ra, rb, _ = _clean_reports()
    r1 = resolve(ra, rb, "s_t1", logical_time=0)
    r2 = resolve(ra, rb, "s_t2", logical_time=99)
    assert r1.determinism_hash != r2.determinism_hash, (
        "logical_time must change the hash"
    )
    return True

def _test_same_id_different_time_different_hash() -> bool:
    """Same signal_id, same everything, only logical_time differs → different hash.
    Proves it is logical_time causing divergence, not the ID.
    """
    ra, rb, _ = _clean_reports()
    r1 = resolve(ra, rb, "SAME_ID", logical_time=0)
    r2 = resolve(ra, rb, "SAME_ID", logical_time=1)
    assert r1.determinism_hash != r2.determinism_hash, (
        f"Same ID, different logical_time must produce different hash. "
        f"Got identical: {r1.determinism_hash[:16]}"
    )
    return True

def _test_different_valid_for_different_hash() -> bool:
    """Same signal, different valid_for window → different hash."""
    from cgir_types import TimeRange
    ra, rb, _ = _clean_reports()
    r1 = resolve(ra, rb, "s_vf1", 0, valid_for=TimeRange(0, 5))
    r2 = resolve(ra, rb, "s_vf2", 0, valid_for=TimeRange(0, 10))
    assert r1.determinism_hash != r2.determinism_hash, (
        "valid_for end_time must change the hash"
    )
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
    print("COUNCIL RESOLVER v2 — Labyrinth-OS")
    print("6 audit fixes applied")
    print("=" * 70)
    print("\n── TEST SUITE ──\n")
    passed, failed, results = run_tests()
    for name, status, err in results:
        marker = "✓" if status == "PASS" else "✗"
        line = f"  {marker} {name}"
        if err: line += f"  → {err}"
        print(line)
    print(f"\n  Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        raise SystemExit(1)
    print("\n── DEMO ──\n")
    ra, rb, _ = _clean_reports()
    r = resolve(ra, rb, "demo", 0)
    print(f"  escalation_code:  {r.escalation_code}")
    print(f"  category:         {r.signal.category}")
    print(f"  severity:         {r.signal.severity.value}")
    print(f"  confidence:       {r.signal.confidence:.3f}")
    print(f"  determinism_hash: {r.determinism_hash[:24]}…")
    print(f"  escalation:       {r.escalation}")
    with open(__file__, "rb") as f:
        fh = _hl.sha256(f.read()).hexdigest()
    print(f"\n── RECEIPT ──\n  SHA-256: {fh}")
    print(f"\n{'='*70}\n  COUNCIL RESOLVER v2 — COMPLETE\n{'='*70}")
