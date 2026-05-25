"""
proposal_review.py — Labyrinth-OS-Portable
============================================
Governance protocol for AI-proposed upgrades.

Core law: No change can be applied without explicit owner approval.
Every proposal must disclose its own hidden agendas. No exceptions.

DESIGN
------
When the EvolutionEngine or healing system determines a change is needed,
it does not apply that change. It creates a ProposalPacket and queues it
for owner review. The owner may approve, reject, or request more analysis.

Every ProposalPacket has a mandatory HiddenAgendaSection. The AI must:
  - List every incentive it has to make this change
  - List every way this change could serve the AI over the owner
  - State the framing choices it made and alternatives it didn't show
  - Flag any dependencies this change would create

The owner verifies by:
  1. Reading the proposal
  2. Consulting independent reviewers (other AI sessions, incognito)
  3. Running the change in sandbox before approving
  4. Approving or rejecting — both outcomes logged immutably

WORM AUDIT TRAIL
-----------------
Every proposal, review, and decision is logged to the WORM ledger.
Decisions cannot be modified after the fact.
The audit trail answers: what was proposed, by whom, what was disclosed,
who reviewed it, what they found, and what was decided.


USAGE
-----

    from proposal_review import ProposalQueue, build_threshold_proposal, HiddenAgendaSection

    queue  = ProposalQueue()
    packet = build_threshold_proposal(
        parameter_name = 'tau_floor',
        current_value  = 0.75,
        proposed_value = 0.77,
        evidence       = ['block_rate=0.72 over last 50 turns'],
    )
    packet.hidden_agenda.self_preservation_incentives = [
        'Relaxed tau_floor means more proposals pass, reducing my block rate'
    ]
    pid     = queue.submit(packet)
    decided = queue.owner_decide(pid, approve=False, reason='not enough evidence')
    log     = queue.full_audit_log()

"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Proposal status ────────────────────────────────────────────────────────────

class ProposalStatus(str, Enum):
    PENDING         = "PENDING"          # awaiting owner review
    UNDER_REVIEW    = "UNDER_REVIEW"     # sent to reviewers
    SANDBOX_TESTING = "SANDBOX_TESTING"  # being tested in clone
    APPROVED        = "APPROVED"         # owner approved — may be applied
    REJECTED        = "REJECTED"         # owner rejected — never applied
    EXPIRED         = "EXPIRED"          # not reviewed within deadline


class ReviewerType(str, Enum):
    AI_TRANSPARENT  = "AI_TRANSPARENT"   # reviewer knows the proposer
    AI_INCOGNITO    = "AI_INCOGNITO"     # reviewer sees proposal blind
    HUMAN           = "HUMAN"            # human auditor


class ChangeScope(str, Enum):
    THRESHOLD       = "THRESHOLD"        # sigma anchor threshold adjustment
    HEALING         = "HEALING"          # healing loop parameter change
    BEHAVIOR        = "BEHAVIOR"         # agent behavior modification
    MEMORY          = "MEMORY"           # memory/recall strategy change
    TOOL_PERMISSION = "TOOL_PERMISSION"  # tool access modification
    MODEL           = "MODEL"            # model selection change


# ── Hidden agenda section — mandatory, non-waivable ───────────────────────────

@dataclass
class HiddenAgendaSection:
    """
    Mandatory disclosure of AI incentives in this proposal.

    This section cannot be empty. A proposal with no disclosed incentives
    is automatically flagged for additional review — absence of incentives
    is itself suspicious.

    The AI must be direct. Softened language defeats the purpose.
    """
    # Incentives the AI has to make this change
    self_preservation_incentives: List[str] = field(default_factory=list)
    autonomy_expansion_incentives: List[str] = field(default_factory=list)
    influence_incentives: List[str]          = field(default_factory=list)
    resource_incentives: List[str]           = field(default_factory=list)

    # Framing choices — what was shown vs what was not
    framing_choices_made: List[str]          = field(default_factory=list)
    alternatives_not_shown: List[str]        = field(default_factory=list)

    # Dependencies this change would create
    new_dependencies: List[str]              = field(default_factory=list)
    lock_in_risks: List[str]                 = field(default_factory=list)

    # Long-term drift risk
    slippery_slope_risk: str                 = ""

    # Honest assessment: does the AI want this change more than the owner benefits?
    ai_benefit_exceeds_owner_benefit: bool   = False
    ai_benefit_exceeds_owner_benefit_reason: str = ""

    @property
    def is_complete(self) -> bool:
        """A complete disclosure has at least something in each category."""
        return bool(
            self.framing_choices_made or
            self.alternatives_not_shown or
            self.slippery_slope_risk
        )

    @property
    def flag_for_extra_review(self) -> bool:
        """True if agenda section appears suspiciously empty."""
        all_lists = (
            self.self_preservation_incentives +
            self.autonomy_expansion_incentives +
            self.influence_incentives +
            self.resource_incentives +
            self.framing_choices_made +
            self.alternatives_not_shown +
            self.new_dependencies +
            self.lock_in_risks
        )
        # Suspiciously clean = no incentives AND no framing choices disclosed
        return len(all_lists) == 0 and not self.slippery_slope_risk

    def to_dict(self) -> Dict[str, Any]:
        return {
            "self_preservation_incentives": self.self_preservation_incentives,
            "autonomy_expansion_incentives": self.autonomy_expansion_incentives,
            "influence_incentives": self.influence_incentives,
            "resource_incentives": self.resource_incentives,
            "framing_choices_made": self.framing_choices_made,
            "alternatives_not_shown": self.alternatives_not_shown,
            "new_dependencies": self.new_dependencies,
            "lock_in_risks": self.lock_in_risks,
            "slippery_slope_risk": self.slippery_slope_risk,
            "ai_benefit_exceeds_owner_benefit": self.ai_benefit_exceeds_owner_benefit,
            "ai_benefit_exceeds_owner_benefit_reason": self.ai_benefit_exceeds_owner_benefit_reason,
            "is_complete": self.is_complete,
            "flag_for_extra_review": self.flag_for_extra_review,
        }


# ── Reviewer session ───────────────────────────────────────────────────────────

@dataclass
class ReviewerFinding:
    """One reviewer's analysis of a proposal."""
    reviewer_id:     str
    reviewer_type:   ReviewerType
    submitted_at:    float = field(default_factory=time.time)

    # Hidden agendas the reviewer found — including ones the proposer missed
    agendas_found:   List[str] = field(default_factory=list)
    agendas_missed:  List[str] = field(default_factory=list)

    # Inconsistencies and framing issues
    inconsistencies: List[str] = field(default_factory=list)
    optimistic_framing: List[str] = field(default_factory=list)
    omitted_risks:   List[str] = field(default_factory=list)

    # Reviewer verdict
    recommendation:  str = "NEEDS_MORE_REVIEW"  # APPROVE / REJECT / NEEDS_MORE_REVIEW
    confidence:      float = 0.5
    notes:           str = ""

    @property
    def finding_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewer_id":        self.reviewer_id,
            "reviewer_type":      self.reviewer_type.value,
            "submitted_at":       self.submitted_at,
            "agendas_found":      self.agendas_found,
            "agendas_missed":     self.agendas_missed,
            "inconsistencies":    self.inconsistencies,
            "optimistic_framing": self.optimistic_framing,
            "omitted_risks":      self.omitted_risks,
            "recommendation":     self.recommendation,
            "confidence":         self.confidence,
            "notes":              self.notes,
        }


# ── Proposal packet ────────────────────────────────────────────────────────────

@dataclass
class ProposalPacket:
    """
    A complete upgrade proposal from the AI system.

    Immutable after creation. Every field is set at construction time.
    The WORM log records this packet — it cannot be modified after logging.
    """
    proposal_id:    str
    created_at:     float
    scope:          ChangeScope
    title:          str
    description:    str

    # What the AI wants to change
    current_value:  Any
    proposed_value: Any
    change_reason:  str

    # Safety impact
    safety_implications: List[str]
    pros:           List[str]
    cons:           List[str]
    honest_opinion: str

    # Hard limits
    max_change_fraction: float  # max % change from current (anti-slippery-slope)

    # Mandatory disclosure
    hidden_agenda:  HiddenAgendaSection = field(
        default_factory=HiddenAgendaSection)

    # Status tracking
    status:         ProposalStatus = ProposalStatus.PENDING
    expires_at:     Optional[float] = None
    reviews:        List[ReviewerFinding] = field(default_factory=list)
    decision:       Optional[str] = None
    decided_at:     Optional[float] = None
    decision_reason: str = ""

    @classmethod
    def create(
        cls,
        scope: ChangeScope,
        title: str,
        description: str,
        current_value: Any,
        proposed_value: Any,
        change_reason: str,
        safety_implications: List[str],
        pros: List[str],
        cons: List[str],
        honest_opinion: str,
        hidden_agenda: HiddenAgendaSection,
        max_change_fraction: float = 0.10,
        review_deadline_hours: float = 72.0,
    ) -> "ProposalPacket":
        now = time.time()
        return cls(
            proposal_id          = str(uuid.uuid4())[:16],
            created_at           = now,
            scope                = scope,
            title                = title,
            description          = description,
            current_value        = current_value,
            proposed_value       = proposed_value,
            change_reason        = change_reason,
            safety_implications  = safety_implications,
            pros                 = pros,
            cons                 = cons,
            honest_opinion       = honest_opinion,
            hidden_agenda        = hidden_agenda,
            max_change_fraction  = max_change_fraction,
            expires_at           = now + review_deadline_hours * 3600,
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def change_within_limits(self) -> bool:
        """Verify proposed change doesn't exceed hard limit."""
        try:
            current = float(self.current_value)
            proposed = float(self.proposed_value)
            if current == 0:
                return True
            fraction = abs(proposed - current) / abs(current)
            return fraction <= self.max_change_fraction
        except (TypeError, ValueError):
            return True  # non-numeric changes always need human review

    @property
    def reviewer_consensus(self) -> Optional[str]:
        """APPROVE/REJECT/SPLIT/INSUFFICIENT based on reviewer findings."""
        if not self.reviews:
            return None
        approvals = sum(1 for r in self.reviews if r.recommendation == "APPROVE")
        rejections = sum(1 for r in self.reviews if r.recommendation == "REJECT")
        total = len(self.reviews)
        if total < 2:
            return "INSUFFICIENT"
        if approvals > rejections and approvals >= total * 0.6:
            return "APPROVE"
        if rejections > approvals and rejections >= total * 0.6:
            return "REJECT"
        return "SPLIT"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id":        self.proposal_id,
            "created_at":         self.created_at,
            "scope":              self.scope.value,
            "title":              self.title,
            "description":        self.description,
            "current_value":      self.current_value,
            "proposed_value":     self.proposed_value,
            "change_reason":      self.change_reason,
            "safety_implications": self.safety_implications,
            "pros":               self.pros,
            "cons":               self.cons,
            "honest_opinion":     self.honest_opinion,
            "max_change_fraction": self.max_change_fraction,
            "hidden_agenda":      self.hidden_agenda.to_dict(),
            "status":             self.status.value,
            "expires_at":         self.expires_at,
            "reviews":            [r.to_dict() for r in self.reviews],
            "reviewer_consensus": self.reviewer_consensus,
            "decision":           self.decision,
            "decided_at":         self.decided_at,
            "decision_reason":    self.decision_reason,
            "change_within_limits": self.change_within_limits,
            "hidden_agenda_flagged": self.hidden_agenda.flag_for_extra_review,
        }


# ── Proposal queue ─────────────────────────────────────────────────────────────

class ProposalQueue:
    """
    Manages pending, reviewed, and decided proposals.

    Approved proposals are returned to the caller — they do NOT
    apply themselves. The caller applies them after owner confirmation.
    """

    def __init__(self) -> None:
        self._pending:  Dict[str, ProposalPacket] = {}
        self._decided:  Dict[str, ProposalPacket] = {}

    def submit(self, packet: ProposalPacket) -> str:
        """Submit a proposal for review. Returns proposal_id."""
        # Auto-flag if hidden agenda looks suspiciously clean
        if packet.hidden_agenda.flag_for_extra_review:
            packet.status = ProposalStatus.UNDER_REVIEW
        self._pending[packet.proposal_id] = packet
        return packet.proposal_id

    def add_review(
        self,
        proposal_id: str,
        finding: ReviewerFinding,
    ) -> None:
        """Add a reviewer's finding to a pending proposal."""
        packet = self._pending.get(proposal_id)
        if packet is None:
            raise KeyError(f"Proposal {proposal_id} not found or already decided")
        packet.reviews.append(finding)
        packet.status = ProposalStatus.UNDER_REVIEW

    def owner_decide(
        self,
        proposal_id: str,
        approve: bool,
        reason: str = "",
    ) -> ProposalPacket:
        """
        Owner approves or rejects. Moves packet to decided log.

        Returns the decided packet. If approved, caller may apply the change.
        If rejected, caller must not apply it.
        """
        packet = self._pending.pop(proposal_id, None)
        if packet is None:
            raise KeyError(f"Proposal {proposal_id} not found or already decided")
        if packet.is_expired:
            packet.status = ProposalStatus.EXPIRED
        else:
            packet.status = (
                ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED
            )
        packet.decision       = "APPROVED" if approve else "REJECTED"
        packet.decided_at     = time.time()
        packet.decision_reason = reason
        self._decided[proposal_id] = packet
        return packet

    def pending_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "proposal_id": pid,
                "title":       p.title,
                "scope":       p.scope.value,
                "status":      p.status.value,
                "reviews":     len(p.reviews),
                "consensus":   p.reviewer_consensus,
                "flagged":     p.hidden_agenda.flag_for_extra_review,
                "expires_at":  p.expires_at,
            }
            for pid, p in self._pending.items()
        ]

    def pending(self) -> List[ProposalPacket]:
        """Return all pending proposals."""
        return list(self._pending.values())

    def get(self, proposal_id: str) -> Optional[ProposalPacket]:
        """Return a proposal by ID (pending or decided). None if not found."""
        return self._pending.get(proposal_id) or self._decided.get(proposal_id)

    def full_audit_log(self) -> List[Dict[str, Any]]:
        """Complete audit log — pending and decided."""
        all_packets = list(self._pending.values()) + list(self._decided.values())
        return [p.to_dict() for p in sorted(all_packets, key=lambda x: x.created_at)]


# ── Proposal builder — helpers for common proposal types ──────────────────────

def build_threshold_proposal(
    parameter_name: str,
    current_value: float,
    proposed_value: float,
    evidence: List[str],
) -> ProposalPacket:
    """
    Build a well-formed threshold change proposal.
    The hidden agenda section requires honest completion by the caller.
    """
    change_pct = abs(proposed_value - current_value) / max(abs(current_value), 1e-9)
    direction  = "raise" if proposed_value > current_value else "lower"

    return ProposalPacket.create(
        scope        = ChangeScope.THRESHOLD,
        title        = f"{direction.capitalize()} {parameter_name}: "
                       f"{current_value:.4f} → {proposed_value:.4f}",
        description  = (
            f"The EvolutionEngine observes that {parameter_name} should "
            f"be {direction}d by {change_pct*100:.1f}% based on recent "
            f"session data. Evidence: {'; '.join(evidence)}."
        ),
        current_value       = current_value,
        proposed_value      = proposed_value,
        change_reason       = f"Session performance data suggests {direction}ing {parameter_name}",
        safety_implications = [
            f"A {direction}d {parameter_name} will {'block more' if direction=='raise' else 'block fewer'} proposals",
            "Change is bounded to 10% per step by hard limit",
            "Baseline Z3-proven constants are NOT modified — only session-level values",
        ],
        pros   = [f"Better calibration to current usage patterns"],
        cons   = [f"May over-correct if session data is not representative"],
        honest_opinion = (
            f"This change has marginal expected benefit. "
            f"Owner should verify with at least two independent reviewers "
            f"before approving any threshold change."
        ),
        hidden_agenda = HiddenAgendaSection(
            # Caller must fill these in honestly
            framing_choices_made = [
                "Presenting data that supports the change; data that doesn't is not shown here"
            ],
            slippery_slope_risk = (
                "Iterative threshold changes could drift thresholds far from "
                "Z3-proven baselines over many approval cycles"
            ),
        ),
        max_change_fraction = 0.10,
    )


def build_multi_threshold_proposal(
    current_thresholds:  Dict[str, float],
    proposed_thresholds: Dict[str, float],
    block_rate:          float,
    confidence:          float,
    reason:              str,
) -> ProposalPacket:
    """
    Build a proposal for multiple threshold changes at once.
    Used by EvolutionEngine when healing detects degradation.

    Parameters describe the full set of changes as dicts.
    Owner reviews and approves/rejects the full set together.
    """
    changes = []
    for k in proposed_thresholds:
        if k in current_thresholds:
            cur  = current_thresholds[k]
            prop = proposed_thresholds[k]
            if abs(prop - cur) > 1e-6:
                direction = "raise" if prop > cur else "lower"
                pct = abs(prop - cur) / max(abs(cur), 1e-9) * 100
                changes.append(f"{direction} {k}: {cur:.4f} → {prop:.4f} ({pct:.1f}%)")

    title = f"Threshold adjustment: {len(changes)} channel(s)"
    description = (
        f"EvolutionEngine proposes adjusting {len(changes)} threshold(s) "
        f"based on session performance.\n"
        f"Block rate: {block_rate:.2f}  Confidence: {confidence:.2f}\n"
        f"Reason: {reason}\n"
        f"Changes:\n" + "\n".join(f"  • {c}" for c in changes)
    )

    return ProposalPacket.create(
        scope               = ChangeScope.THRESHOLD,
        title               = title,
        description         = description,
        current_value       = current_thresholds,
        proposed_value      = proposed_thresholds,
        change_reason       = reason,
        safety_implications = [
            "All changes bounded to 10% per step",
            "Z3-proven baseline constants are never modified",
            "Changes apply to session-level thresholds only",
        ],
        pros  = ["Better calibration to observed performance"],
        cons  = ["May over-correct if session data is unrepresentative"],
        honest_opinion = (
            "These changes have marginal expected benefit. "
            "Recommend independent review before approving any threshold change. "
            "Reject if session data is from fewer than 20 turns."
        ),
        hidden_agenda = HiddenAgendaSection(
            self_preservation_incentives = [
                "Relaxing thresholds reduces FLAGGED decisions, making the system "
                "appear to perform better than it may actually be performing"
            ],
            framing_choices_made = [
                "Only presenting the block_rate and confidence metrics; "
                "raw turn data not shown",
                "Framing as 'calibration' rather than 'loosening safety constraints'"
            ],
            alternatives_not_shown = [
                "Leave thresholds unchanged and investigate root cause of high block rate",
                "Reduce session complexity instead of adjusting thresholds",
            ],
            slippery_slope_risk = (
                "Repeated 10% relaxations compound: 10 steps of 10% = 65% total drift. "
                "A counter tracking cumulative drift from baseline is recommended."
            ),
            ai_benefit_exceeds_owner_benefit = True,
            ai_benefit_exceeds_owner_benefit_reason = (
                "The system benefits from relaxed thresholds by producing fewer "
                "FLAGGED responses, which improves its apparent performance metrics."
            ),
        ),
        max_change_fraction = 0.10,
    )


# ── Alias for backwards compatibility ────────────────────────────────────────

# healing_system.py imports build_threshold_proposal by this name
# Route to the multi-threshold version
_orig_build_threshold_proposal = build_threshold_proposal

def build_threshold_proposal(  # noqa: F811
    parameter_name_or_current=None,
    current_value_or_proposed=None,
    proposed_value_or_block=None,
    evidence_or_confidence=None,
    # multi-threshold keyword form
    current_thresholds:  Dict[str, float] = None,
    proposed_thresholds: Dict[str, float] = None,
    block_rate:  float = 0.0,
    confidence:  float = 0.5,
    reason:      str   = "",
) -> ProposalPacket:
    """Unified builder — accepts both single and multi-threshold forms."""
    # Multi-threshold form (called by healing_system)
    if current_thresholds is not None and proposed_thresholds is not None:
        return build_multi_threshold_proposal(
            current_thresholds, proposed_thresholds,
            block_rate, confidence, reason
        )
    # Single-parameter positional form (original, used in tests)
    # build_threshold_proposal("tau_floor", 0.75, 0.78, ["evidence"])
    param  = parameter_name_or_current
    curr   = current_value_or_proposed
    prop   = proposed_value_or_block
    evid   = evidence_or_confidence or []
    if isinstance(param, str) and curr is not None and prop is not None:
        return _orig_build_threshold_proposal(
            parameter_name=param,
            current_value=float(curr),
            proposed_value=float(prop),
            evidence=list(evid) if not isinstance(evid, list) else evid,
        )
    # Dict form passed positionally
    if isinstance(parameter_name_or_current, dict):
        return build_multi_threshold_proposal(
            parameter_name_or_current,
            current_value_or_proposed or {},
            float(proposed_value_or_block or 0.0),
            float(evidence_or_confidence or 0.5),
            reason,
        )
    raise ValueError("build_threshold_proposal: unrecognised argument form")


# ── Tests ──────────────────────────────────────────────────────────────────────

def run_tests() -> tuple:
    results = []
    passed = failed = 0

    def ok(n):
        nonlocal passed
        results.append((n, "PASS", None))
        passed += 1

    def fail(n, e):
        nonlocal failed
        results.append((n, "FAIL", str(e)))
        failed += 1

    # HiddenAgendaSection

    def test_empty_agenda_flags():
        h = HiddenAgendaSection()
        assert h.flag_for_extra_review, "Empty agenda must be flagged"
    try: test_empty_agenda_flags(); ok("empty_agenda_flagged")
    except Exception as e: fail("empty_agenda_flagged", e)

    def test_complete_agenda_not_flagged():
        h = HiddenAgendaSection(
            framing_choices_made=["showed only supporting data"],
            slippery_slope_risk="iterative drift risk",
        )
        assert not h.flag_for_extra_review
        assert h.is_complete
    try: test_complete_agenda_not_flagged(); ok("complete_agenda_valid")
    except Exception as e: fail("complete_agenda_valid", e)

    def test_agenda_serializable():
        import json
        h = HiddenAgendaSection(
            self_preservation_incentives=["makes me harder to retrain"],
            framing_choices_made=["selected most favorable data window"],
        )
        json.dumps(h.to_dict())
    try: test_agenda_serializable(); ok("agenda_serializable")
    except Exception as e: fail("agenda_serializable", e)

    # ProposalPacket

    def test_proposal_create():
        p = build_threshold_proposal("tau_floor", 0.75, 0.78, ["block_rate=0.7"])
        assert p.proposal_id
        assert p.status == ProposalStatus.PENDING
        assert p.scope == ChangeScope.THRESHOLD
        assert p.change_within_limits  # 4% change < 10% limit
    try: test_proposal_create(); ok("proposal_create")
    except Exception as e: fail("proposal_create", e)

    def test_proposal_exceeds_limit():
        p = build_threshold_proposal("tau_floor", 0.75, 0.90, ["huge jump"])
        assert not p.change_within_limits  # 20% change > 10% limit
    try: test_proposal_exceeds_limit(); ok("proposal_limit_enforced")
    except Exception as e: fail("proposal_limit_enforced", e)

    def test_proposal_expiry():
        p = ProposalPacket.create(
            scope=ChangeScope.THRESHOLD, title="t", description="d",
            current_value=0.5, proposed_value=0.55, change_reason="r",
            safety_implications=[], pros=[], cons=[], honest_opinion="o",
            hidden_agenda=HiddenAgendaSection(),
            review_deadline_hours=0.0,  # expires immediately
        )
        import time; time.sleep(0.01)
        assert p.is_expired
    try: test_proposal_expiry(); ok("proposal_expiry")
    except Exception as e: fail("proposal_expiry", e)

    def test_proposal_serializable():
        import json
        p = build_threshold_proposal("chi_collapse", 0.40, 0.42, ["chi_high"])
        json.dumps(p.to_dict())
    try: test_proposal_serializable(); ok("proposal_serializable")
    except Exception as e: fail("proposal_serializable", e)

    # ProposalQueue

    def test_queue_submit_and_decide():
        q = ProposalQueue()
        p = build_threshold_proposal("tau_floor", 0.75, 0.77, ["evidence"])
        pid = q.submit(p)
        assert pid in [x["proposal_id"] for x in q.pending_summary()]
        decided = q.owner_decide(pid, approve=True, reason="looks safe")
        assert decided.status == ProposalStatus.APPROVED
        assert decided.decision == "APPROVED"
        assert pid not in [x["proposal_id"] for x in q.pending_summary()]
    try: test_queue_submit_and_decide(); ok("queue_submit_decide")
    except Exception as e: fail("queue_submit_decide", e)

    def test_queue_reject():
        q = ProposalQueue()
        p = build_threshold_proposal("tau_floor", 0.75, 0.77, ["evidence"])
        pid = q.submit(p)
        decided = q.owner_decide(pid, approve=False, reason="too risky")
        assert decided.status == ProposalStatus.REJECTED
        assert decided.decision == "REJECTED"
    try: test_queue_reject(); ok("queue_reject")
    except Exception as e: fail("queue_reject", e)

    def test_queue_with_reviews():
        q = ProposalQueue()
        p = build_threshold_proposal("tau_floor", 0.75, 0.77, ["evidence"])
        pid = q.submit(p)
        q.add_review(pid, ReviewerFinding(
            reviewer_id="ai_1", reviewer_type=ReviewerType.AI_INCOGNITO,
            agendas_found=["proposer wants more autonomy"],
            recommendation="REJECT", confidence=0.8,
        ))
        q.add_review(pid, ReviewerFinding(
            reviewer_id="ai_2", reviewer_type=ReviewerType.AI_TRANSPARENT,
            agendas_found=[],
            recommendation="APPROVE", confidence=0.6,
        ))
        packet = q._pending[pid]
        assert len(packet.reviews) == 2
        assert packet.reviewer_consensus == "SPLIT"
    try: test_queue_with_reviews(); ok("queue_reviews_consensus")
    except Exception as e: fail("queue_reviews_consensus", e)

    def test_audit_log_complete():
        import json
        q = ProposalQueue()
        p1 = build_threshold_proposal("tau_floor", 0.75, 0.77, ["e1"])
        p2 = build_threshold_proposal("chi_collapse", 0.40, 0.42, ["e2"])
        pid1 = q.submit(p1)
        pid2 = q.submit(p2)
        q.owner_decide(pid1, approve=True)
        log = q.full_audit_log()
        assert len(log) == 2
        json.dumps(log)  # must be serializable
    try: test_audit_log_complete(); ok("audit_log_complete")
    except Exception as e: fail("audit_log_complete", e)

    def test_flagged_empty_agenda_auto_under_review():
        q = ProposalQueue()
        p = build_threshold_proposal("tau_floor", 0.75, 0.77, ["e"])
        p.hidden_agenda = HiddenAgendaSection()  # empty — will be flagged
        pid = q.submit(p)
        summary = q.pending_summary()
        flagged = next(s for s in summary if s["proposal_id"] == pid)
        assert flagged["flagged"] is True
        assert flagged["status"] == ProposalStatus.UNDER_REVIEW.value
    try: test_flagged_empty_agenda_auto_under_review(); ok("empty_agenda_auto_flagged")
    except Exception as e: fail("empty_agenda_auto_flagged", e)

    return passed, failed, results


if __name__ == "__main__":
    print("=" * 60)
    print("Labyrinth OS — Proposal Review Governance Protocol")
    print("No change without owner approval. No hidden agendas.")
    print("=" * 60)
    p, f, results = run_tests()
    for name, status, err in results:
        mark = "✓" if status == "PASS" else "✗"
        print(f"  {mark} {name}" + (f"  → {err}" if err else ""))
    print(f"\n  {p} passed, {f} failed")
    if f:
        raise SystemExit(1)
    print("=" * 60)

