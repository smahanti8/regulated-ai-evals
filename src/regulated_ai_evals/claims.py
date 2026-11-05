"""The calibration gate: what may be claimed, given what has been calibrated.

This is the module the framework exists for. Everything else is bookkeeping
that makes this decision possible and makes it reviewable afterwards.

The rule the gate enforces:

    A DECISION_DRIVING claim may not rest on a threshold that has not been
    calibrated. `rae run` exits non-zero. The only way past is an accepted
    non-conformance, in writing, attributed to a person, bound to the
    threshold's current value, and carried in the evidence bundle.

Deviation is permitted. Silent deviation is not. That distinction is the whole
of design controls, compressed into one function.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .calibration import (
    AcceptedNonConformance,
    RiskAcceptanceLedger,
    Threshold,
    ThresholdStatus,
)
from .requirements import Requirement, RequirementRegister, RiskClass

# ---------------------------------------------------------------------------
# POLICY
#
# Three judgement calls. They are constants rather than logic because they are
# the part of this file that is a regulatory opinion rather than a mechanism,
# and an opinion should be visible in a diff when it changes.
#
# Reviewed against this repository's own example data and kept as shipped; the
# alternatives and what each would change are recorded in DECISIONS.md, D10.
# ---------------------------------------------------------------------------

REQUIRED_STATUS: dict[RiskClass, ThresholdStatus] = {
    RiskClass.INFORMATIONAL: ThresholdStatus.ASSERTED,
    RiskClass.SUPPORTIVE: ThresholdStatus.INHERITED,
    RiskClass.DECISION_DRIVING: ThresholdStatus.CALIBRATED,
}
"""Weakest threshold provenance each risk class may rest on.

The gradient is the whole policy. Read across it:

INFORMATIONAL needs only ASSERTED — a human chose the number on purpose. That
is a low bar and it is meant to be; the output is advisory and a reader who
disagrees can ignore it. What it excludes is UNCALIBRATED: a number nobody has
ever thought about, which is a different thing from a judgement call.

SUPPORTIVE needs INHERITED — a spec sheet, a published standard, a vendor
limit. Real external authority, gathered under someone else's operating
conditions. Enough for a number a human will see alongside the evidence.

DECISION_DRIVING needs CALIBRATED. Nothing else. If the system is acting, or if
no one will realistically overrule it, the boundary has to have been measured on
data from this system. A spec-sheet limit is not a claim about your detector."""

IN_SAMPLE_DOWNGRADES_TO: ThresholdStatus = ThresholdStatus.ASSERTED
"""What CALIBRATED collapses to when the threshold was fitted and measured on
the same golden set with no held-out confirmation.

ASSERTED rather than INHERITED because an in-sample operating point is not a
weaker measurement of performance — it is a measurement of fit. The number it
produces is a description of the data the threshold was drawn on."""

MAX_CI_WIDTH_FOR_PERFORMANCE_CLAIM: float = 0.20
"""Widest 95% recall interval that may still carry a numeric performance claim.

At 0.20 a claim of "detects 95% of thermal excursions" needs roughly n=70
positives behind it. Below that the point estimate is reported, the claim is
not made. This is the gate that catches 3-for-3 on a ten-row file."""


class ClaimStrength(str, Enum):
    PERFORMANCE = "performance"
    """A quantitative claim: sensitivity, specificity, false-alarm rate."""
    BEHAVIOURAL = "behavioural"
    """A description of what the system does. True, verifiable, and free of any
    assertion about how well it does it."""
    NONE = "none"
    """Nothing is supported — the verifying evidence itself is absent."""


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    requirement_id: str
    risk_class: RiskClass
    claimed: str
    strength: ClaimStrength
    supportable: str
    conforms: bool
    """False when the gate would block the run. Independent of whether an
    acceptance exists — a non-conformance that has been accepted is still a
    non-conformance, and the bundle counts it as one."""
    blocking_thresholds: tuple[str, ...]
    reasons: tuple[str, ...]
    acceptance: AcceptedNonConformance | None = None
    stale_acceptance: AcceptedNonConformance | None = None

    @property
    def blocks_run(self) -> bool:
        return not self.conforms and self.acceptance is None

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "risk_class": self.risk_class.value,
            "claimed": self.claimed,
            "strength": self.strength.value,
            "supportable": self.supportable,
            "conforms": self.conforms,
            "blocks_run": self.blocks_run,
            "blocking_thresholds": list(self.blocking_thresholds),
            "reasons": list(self.reasons),
            "acceptance": self.acceptance.to_dict() if self.acceptance else None,
            "stale_acceptance": (
                self.stale_acceptance.to_dict() if self.stale_acceptance else None
            ),
        }


def effective_status(threshold: Threshold) -> tuple[ThresholdStatus, list[str]]:
    """The status the evidence supports, which may be weaker than the declared one.

    Separated from the gate so the demotion is inspectable on its own: a
    reviewer can ask "why is this CALIBRATED threshold being treated as
    ASSERTED?" and get an answer without reading the gate.
    """
    reasons: list[str] = []
    status = threshold.status
    evidence = threshold.calibration

    if status is ThresholdStatus.CALIBRATED and evidence is not None:
        if evidence.fitted_value != threshold.value:
            status = ThresholdStatus.ASSERTED
            reasons.append(
                f"calibrated at {evidence.fitted_value} {threshold.unit} but the "
                f"source uses {threshold.value}; the evidence describes a value "
                "this system does not run"
            )
        elif evidence.in_sample_only:
            status = IN_SAMPLE_DOWNGRADES_TO
            reasons.append(
                f"fitted and measured on the same golden set "
                f"({evidence.fitted_on}); no held-out confirmation"
            )
    return status, reasons


def supportable_strength(
    requirement: Requirement, thresholds: Sequence[Threshold]
) -> tuple[ClaimStrength, list[str], list[str]]:
    """Strongest claim strength the calibration evidence supports.

    Returns the strength, the ids of thresholds that limited it, and the
    reasons — the reasons being the part that ends up in front of an auditor.
    """
    if not thresholds:
        return ClaimStrength.PERFORMANCE, [], []

    required = REQUIRED_STATUS[requirement.risk_class]
    blocking: list[str] = []
    reasons: list[str] = []
    strength = ClaimStrength.PERFORMANCE

    for threshold in thresholds:
        status, demotions = effective_status(threshold)
        for demotion in demotions:
            reasons.append(f"{threshold.id}: {demotion}")

        if status.rank < required.rank:
            strength = ClaimStrength.BEHAVIOURAL
            blocking.append(threshold.id)
            reasons.append(
                f"{threshold.id} is {status.value}; a "
                f"{requirement.risk_class.value} claim requires {required.value}"
            )
            continue

        # The interval gate applies only where the claim's authority comes from
        # the measurement itself. A SUPPORTIVE claim resting on a spec limit is
        # not making a statistical assertion, so there is no interval to widen.
        if required is not ThresholdStatus.CALIBRATED:
            continue

        evidence = threshold.calibration
        if evidence is None:
            continue
        width = evidence.operating_point.recall_ci_width
        if width > MAX_CI_WIDTH_FOR_PERFORMANCE_CLAIM:
            strength = ClaimStrength.BEHAVIOURAL
            blocking.append(threshold.id)
            low, high = evidence.operating_point.recall_ci
            reasons.append(
                f"{threshold.id}: 95% recall interval [{low:.2f}, {high:.2f}] is "
                f"{width:.2f} wide against a {MAX_CI_WIDTH_FOR_PERFORMANCE_CLAIM:.2f} "
                f"limit (n={evidence.operating_point.positives} positives)"
            )

    return strength, blocking, reasons


def evaluate(
    register: RequirementRegister,
    thresholds: Mapping[str, Threshold],
    ledger: RiskAcceptanceLedger,
    verified: Mapping[str, bool] | None = None,
) -> list[ClaimVerdict]:
    """Produce a verdict for every in-scope requirement."""
    verified = verified or {}
    verdicts: list[ClaimVerdict] = []

    for requirement in register.in_scope():
        attached = [thresholds[t] for t in requirement.thresholds if t in thresholds]
        strength, blocking, reasons = supportable_strength(requirement, attached)

        has_evidence = verified.get(requirement.id, True)
        if not has_evidence:
            strength = ClaimStrength.NONE
            reasons.append("no passing test provides evidence for this requirement")

        conforms = not blocking and has_evidence

        acceptance = None
        stale = None
        for threshold_id in blocking:
            threshold = thresholds[threshold_id]
            found = ledger.find(threshold)
            if found is not None:
                acceptance = found
            else:
                stale = stale or ledger.stale_for(threshold)
                acceptance = None
                break

        if stale is not None:
            reasons.append(
                f"an acceptance for {stale.threshold_id} exists but was granted "
                f"against a different value (hash {stale.threshold_value_hash[:19]}…); "
                "it does not carry over"
            )

        verdicts.append(
            ClaimVerdict(
                requirement_id=requirement.id,
                risk_class=requirement.risk_class,
                claimed=requirement.statement,
                strength=strength,
                supportable=_supportable_text(requirement, strength),
                conforms=conforms,
                blocking_thresholds=tuple(blocking),
                reasons=tuple(reasons),
                acceptance=acceptance,
                stale_acceptance=stale,
            )
        )

    return verdicts


def _supportable_text(requirement: Requirement, strength: ClaimStrength) -> str:
    if strength is ClaimStrength.PERFORMANCE:
        return requirement.statement
    if strength is ClaimStrength.NONE:
        return "Nothing. No passing evidence exists for this claim in this run."
    return requirement.behavioural_statement or (
        "The described behaviour only. No performance characteristic is supported."
    )
