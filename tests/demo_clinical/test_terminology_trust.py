"""Verification suite for the terminology-trust layer, pinned at e61d181.

Scoped deliberately to trust_status.py and terminology.py. The mapping,
quality, store and API layers are declared out of scope in
requirements/clinical-fhir.yaml, so they appear in the matrix as a boundary
rather than as silence.
"""

from __future__ import annotations

import pytest

from regulated_ai_evals import verifies


@verifies("REQ-TX-001")
def test_only_verified_bindings_are_trusted(trust):
    make = lambda status: trust.Binding(  # noqa: E731
        local_code="X", system="s", code="c", display="d", status=status, source="test"
    )
    assert make(trust.BindingStatus.VERIFIED).is_trusted is True
    assert make(trust.BindingStatus.PROVISIONAL).is_trusted is False
    assert make(trust.BindingStatus.DEPRECATED).is_trusted is False


@verifies("REQ-TX-001")
def test_no_shipped_provisional_binding_reports_as_trusted(terminology):
    """The invariant on the real table, not on a constructed example.

    A property test on the enum can pass while a single binding in the shipped
    map has been promoted by hand. This checks the artefact that ships.
    """
    promoted = [
        b.local_code
        for b in terminology.all_bindings()
        if b.is_trusted and b.status is not terminology.BindingStatus.VERIFIED
    ]
    assert promoted == []


@verifies("REQ-TX-002")
@pytest.mark.parametrize(
    "function,argument,domain",
    [
        ("procedure_binding", "RAS-NOPE-99", "procedure"),
        ("observation_binding", "not_a_metric", "observation"),
        ("ucum_unit", "furlongs", "unit"),
        ("procedure_status", "exploded", "procedure-status"),
    ],
)
def test_unknown_code_refuses_rather_than_degrades(
    terminology, function, argument, domain
):
    with pytest.raises(terminology.UnmappedConceptError) as caught:
        getattr(terminology, function)(argument)

    assert caught.value.local_code == argument
    assert caught.value.domain == domain
    assert argument in str(caught.value)


@verifies("REQ-TX-003")
def test_coverage_report_reconciles_with_the_binding_table(terminology):
    report = terminology.coverage_report()
    bindings = terminology.all_bindings()

    assert report["total"] == len(bindings)
    assert report["verified"] + report["provisional"] == report["total"], (
        "verified and provisional do not account for every binding — a status "
        "exists in the table that the governance report does not count"
    )
    assert report["verified"] == sum(
        1 for b in bindings if b.status is terminology.BindingStatus.VERIFIED
    )


@verifies("REQ-TX-004")
def test_administrative_gender_degrades_deliberately(terminology):
    """The documented exception to fail-loud, verified as an exception.

    Asserting this explicitly is the point: the behaviour is defensible, and
    the risk is that a later reader mistakes it for the oversight it resembles.
    """
    assert terminology.administrative_gender(None) == "unknown"
    assert terminology.administrative_gender("not-a-value") == "unknown"


@verifies("REQ-TX-005")
def test_provisional_fraction_is_measured_and_published(terminology):
    """Evidence that the split is reported — not that it is acceptable.

    REQ-TX-005 claims the concept map is fit for clinical exchange. This test
    can only show the fraction is measurable, because nothing in the system
    decides what fraction would be acceptable. The gate is what turns that
    absence into a finding.
    """
    report = terminology.coverage_report()
    assert report["total"] > 0
    assert 0.0 <= report["provisional"] / report["total"] <= 1.0
