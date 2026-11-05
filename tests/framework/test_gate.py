"""The harness's own tests.

Deliberately carry no @verifies marker. The register describes claims about the
systems under test; these assert that the harness works, which is a different
kind of evidence and does not belong in the same matrix. `rae run` executes
only the demo suites for that reason.
"""

from __future__ import annotations

from datetime import date

import pytest

from regulated_ai_evals.calibration import (
    CalibrationEvidence,
    OperatingPoint,
    RiskAcceptanceLedger,
    Threshold,
    ThresholdStatus,
    wilson_interval,
)
from regulated_ai_evals.claims import (
    ClaimStrength,
    effective_status,
    evaluate,
    supportable_strength,
)
from regulated_ai_evals.goldens import GoldenSetRef
from regulated_ai_evals.requirements import (
    Requirement,
    RequirementRegister,
    RiskClass,
    VerificationMethod,
)

REF = GoldenSetRef("g", "1.0.0", "sha256:abc")
HOLDOUT = GoldenSetRef("h", "1.0.0", "sha256:def")


def point(tp=95, fp=5, fn=5, tn=1000) -> OperatingPoint:
    return OperatingPoint(tp, fp, fn, tn)


def threshold(status=ThresholdStatus.ASSERTED, calibration=None, value=90.0, **kw):
    return Threshold(
        id=kw.get("id", "THR-X"),
        value=value,
        unit="degC",
        system="s",
        location="f.py:1",
        status=status,
        source=kw.get("source", ""),
        calibration=calibration,
    )


def requirement(risk_class, thresholds=("THR-X",)) -> Requirement:
    return Requirement(
        id="REQ-1",
        statement="claimed",
        rationale="r",
        risk_class=risk_class,
        verification=VerificationMethod.TEST,
        acceptance="a",
        system="s",
        behavioural_statement="behaviour only",
        thresholds=thresholds,
    )


def calibrated(value=90.0, confirmed=HOLDOUT, op=None) -> CalibrationEvidence:
    return CalibrationEvidence(
        fitted_on=REF,
        fitted_value=value,
        objective="max recall",
        operating_point=op or point(),
        fitted_date=date(2026, 9, 14),
        confirmed_on=confirmed,
    )


# -- the gradient ----------------------------------------------------------


@pytest.mark.parametrize(
    "risk_class,status,expected",
    [
        (RiskClass.INFORMATIONAL, ThresholdStatus.UNCALIBRATED, ClaimStrength.BEHAVIOURAL),
        (RiskClass.INFORMATIONAL, ThresholdStatus.ASSERTED, ClaimStrength.PERFORMANCE),
        (RiskClass.SUPPORTIVE, ThresholdStatus.ASSERTED, ClaimStrength.BEHAVIOURAL),
        (RiskClass.SUPPORTIVE, ThresholdStatus.INHERITED, ClaimStrength.PERFORMANCE),
        (RiskClass.DECISION_DRIVING, ThresholdStatus.INHERITED, ClaimStrength.BEHAVIOURAL),
    ],
)
def test_required_status_scales_with_risk_class(risk_class, status, expected):
    source = "ISO 10816" if status is ThresholdStatus.INHERITED else ""
    strength, _, _ = supportable_strength(
        requirement(risk_class), [threshold(status=status, source=source)]
    )
    assert strength is expected


def test_decision_driving_claim_passes_on_calibrated_threshold():
    strength, blocking, _ = supportable_strength(
        requirement(RiskClass.DECISION_DRIVING),
        [threshold(status=ThresholdStatus.CALIBRATED, calibration=calibrated())],
    )
    assert strength is ClaimStrength.PERFORMANCE
    assert blocking == []


def test_claim_with_no_thresholds_is_unconstrained():
    """A categorical safety property needs no numeric boundary to be evidenced."""
    strength, blocking, reasons = supportable_strength(
        requirement(RiskClass.DECISION_DRIVING, thresholds=()), []
    )
    assert (strength, blocking, reasons) == (ClaimStrength.PERFORMANCE, [], [])


# -- demotions -------------------------------------------------------------


def test_in_sample_calibration_is_demoted():
    status, reasons = effective_status(
        threshold(
            status=ThresholdStatus.CALIBRATED, calibration=calibrated(confirmed=None)
        )
    )
    assert status is ThresholdStatus.ASSERTED
    assert "no held-out confirmation" in reasons[0]


def test_calibration_at_a_value_the_code_does_not_use_is_demoted():
    """The recorded exercise concluded 5.4; nobody edited the constant."""
    status, reasons = effective_status(
        threshold(
            value=5.0,
            status=ThresholdStatus.CALIBRATED,
            calibration=calibrated(value=5.4),
        )
    )
    assert status is ThresholdStatus.ASSERTED
    assert "does not run" in reasons[0]


def test_wide_interval_blocks_a_performance_claim():
    strength, blocking, reasons = supportable_strength(
        requirement(RiskClass.DECISION_DRIVING),
        [
            threshold(
                status=ThresholdStatus.CALIBRATED,
                calibration=calibrated(op=point(tp=3, fp=0, fn=0, tn=7)),
            )
        ],
    )
    assert strength is ClaimStrength.BEHAVIOURAL
    assert blocking == ["THR-X"]
    assert "wide against" in reasons[-1]


def test_wilson_interval_does_not_collapse_at_the_boundary():
    """3-for-3 is not certainty. The normal approximation would say it is."""
    low, high = wilson_interval(3, 3)
    assert low < 0.5 and high == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


# -- acceptances -----------------------------------------------------------


def register_with(risk_class) -> RequirementRegister:
    return RequirementRegister({"REQ-1": requirement(risk_class)})


def test_uncalibrated_threshold_blocks_a_decision_driving_run():
    verdicts = evaluate(
        register_with(RiskClass.DECISION_DRIVING),
        {"THR-X": threshold()},
        RiskAcceptanceLedger(),
    )
    assert verdicts[0].blocks_run is True
    assert verdicts[0].supportable == "behaviour only"


def test_written_acceptance_unblocks_but_stays_a_nonconformance():
    subject = threshold()
    ledger = RiskAcceptanceLedger()
    ledger.accept(subject, "field data pending; interim inspection regime", "QA Lead")

    verdict = evaluate(
        register_with(RiskClass.DECISION_DRIVING), {"THR-X": subject}, ledger
    )[0]

    assert verdict.blocks_run is False
    assert verdict.conforms is False, "an accepted deviation is still a deviation"
    assert verdict.acceptance.accepted_by == "QA Lead"


def test_acceptance_does_not_carry_over_when_the_value_moves():
    ledger = RiskAcceptanceLedger()
    ledger.accept(threshold(value=90.0), "signed for 90", "QA Lead")

    moved = threshold(value=95.0)
    assert ledger.find(moved) is None
    assert ledger.stale_for(moved) is not None

    verdict = evaluate(
        register_with(RiskClass.DECISION_DRIVING), {"THR-X": moved}, ledger
    )[0]
    assert verdict.blocks_run is True
    assert "does not carry over" in verdict.reasons[-1]


def test_missing_evidence_reduces_the_claim_to_nothing():
    verdict = evaluate(
        register_with(RiskClass.INFORMATIONAL),
        {"THR-X": threshold()},
        RiskAcceptanceLedger(),
        verified={"REQ-1": False},
    )[0]
    assert verdict.strength is ClaimStrength.NONE
    assert verdict.blocks_run is True


def test_calibrated_status_cannot_be_asserted_without_evidence():
    with pytest.raises(ValueError, match="derived from the evidence"):
        threshold(status=ThresholdStatus.CALIBRATED)


def test_inherited_status_requires_naming_the_authority():
    with pytest.raises(ValueError, match="Inherited from where"):
        threshold(status=ThresholdStatus.INHERITED)
