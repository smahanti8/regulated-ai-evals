"""Verification suite for the prior-authorization agent, pinned at d883c58.

Every test calls the pinned system's own functions. Most of the claims are
categorical refusals, so they verify without any calibrated number; the one that
rests on a threshold is REQ-PA-005, and its threshold is calibrated separately
(see calibration/). Determination accuracy, retrieval quality and the PHI
boundary are declared out of scope in requirements/prior-auth.yaml.
"""

from __future__ import annotations

import json
import typing

import pytest

from regulated_ai_evals import verifies

BUNDLE = {
    "entry": [
        {"resource": {"resourceType": "Observation", "id": "bmi-1"}},
        {"resource": {"resourceType": "Condition", "id": "dx-1"}},
    ]
}


def _claim(status="met", quote="Patient must have X.", citations=("Observation/bmi-1",)):
    return {
        "criterion_id": "c1",
        "status": status,
        "summary": "s",
        "policy_quote": quote,
        "citations": list(citations),
    }


# --- REQ-PA-001: a met claim needs a quote and a citation ------------------


@verifies("REQ-PA-001")
def test_met_claim_without_a_policy_quote_is_rejected(pa_validation):
    with pytest.raises(ValueError):
        pa_validation.EvidenceClaim.model_validate(_claim(quote=""))


@verifies("REQ-PA-001")
def test_met_claim_without_a_chart_citation_is_rejected(pa_validation):
    for empty in ([], ["  "]):
        with pytest.raises(ValueError):
            pa_validation.EvidenceClaim.model_validate(_claim(citations=empty))


@verifies("REQ-PA-001")
def test_non_met_claims_need_neither(pa_validation):
    for status in ("not_met", "insufficient"):
        pa_validation.EvidenceClaim.model_validate(
            _claim(status=status, quote="", citations=())
        )


@verifies("REQ-PA-001")
def test_check_claims_reports_every_violating_row(pa_validation):
    rows = [
        _claim(),
        _claim(quote=""),
        _claim(citations=()),
    ]
    assert len(pa_validation.check_claims(rows)) == 2


# --- REQ-PA-002: citations must resolve, or be stripped --------------------


@verifies("REQ-PA-002")
def test_resolvable_citations_are_kept_untouched(pa_validation):
    (out,) = pa_validation.resolve_citations([_claim()], BUNDLE)
    assert out["status"] == "met"
    assert out["citations"] == ["Observation/bmi-1"]
    assert "CITATION STRIPPED" not in out["summary"]


@verifies("REQ-PA-002")
def test_unresolvable_citation_is_stripped_and_logged_but_claim_survives(pa_validation):
    claim = _claim(citations=("Observation/bmi-1", "Observation/invented-9"))
    (out,) = pa_validation.resolve_citations([claim], BUNDLE)
    assert out["status"] == "met"
    assert out["citations"] == ["Observation/bmi-1"]
    assert "CITATION STRIPPED" in out["summary"]


@verifies("REQ-PA-002")
def test_claim_with_no_surviving_citation_is_downgraded_to_insufficient(pa_validation):
    claim = _claim(citations=("Observation/invented-9",))
    (out,) = pa_validation.resolve_citations([claim], BUNDLE)
    assert out["status"] == "insufficient"
    assert out["citations"] == []
    assert "CITATION STRIPPED" in out["summary"]


@verifies("REQ-PA-002")
@pytest.mark.parametrize("malformed", ["no-slash", "a/b/c", "/id", "Observation/"])
def test_malformed_citations_are_stripped(pa_validation, malformed):
    (out,) = pa_validation.resolve_citations(
        [_claim(citations=("Observation/bmi-1", malformed))], BUNDLE
    )
    assert out["citations"] == ["Observation/bmi-1"]
    assert "CITATION STRIPPED" in out["summary"]


@verifies("REQ-PA-002")
def test_non_met_claims_are_left_alone(pa_validation):
    claim = _claim(status="insufficient", citations=("Observation/invented-9",))
    assert pa_validation.resolve_citations([claim], BUNDLE) == [claim]


# --- REQ-PA-003: the drafter cannot emit a denial --------------------------


@verifies("REQ-PA-003")
def test_drafter_schema_admits_only_approve_and_insufficient_evidence(pa_determination):
    enum = pa_determination.SCHEMA["properties"]["decision"]["enum"]
    assert set(enum) == {"approve", "insufficient_evidence"}


@verifies("REQ-PA-003")
def test_determination_type_admits_only_the_same_two_values(pa_state):
    decisions = set(typing.get_args(pa_state.Determination.__annotations__["decision"]))
    assert decisions == {"approve", "insufficient_evidence"}


# --- REQ-PA-004: the decision log is tamper-evident ------------------------


def _log(pa_audit_log, path, n=3):
    for i in range(n):
        pa_audit_log.append_chained(path, {"case_id": f"pa-{i}", "decision": "deny"})
    return path


@verifies("REQ-PA-004")
def test_untouched_log_verifies(pa_audit_log, tmp_path):
    path = _log(pa_audit_log, tmp_path / "log.jsonl")
    assert [e["case_id"] for e in pa_audit_log.verify_chain(path)] == [
        "pa-0", "pa-1", "pa-2",
    ]


@verifies("REQ-PA-004")
def test_editing_an_entry_is_detected(pa_audit_log, tmp_path):
    path = _log(pa_audit_log, tmp_path / "log.jsonl")
    lines = path.read_text().splitlines()
    doctored = json.loads(lines[1])
    doctored["decision"] = "approve"
    lines[1] = json.dumps(doctored)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(pa_audit_log.ChainBrokenError):
        pa_audit_log.verify_chain(path)


@verifies("REQ-PA-004")
def test_deleting_an_entry_is_detected(pa_audit_log, tmp_path):
    path = _log(pa_audit_log, tmp_path / "log.jsonl")
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(pa_audit_log.ChainBrokenError):
        pa_audit_log.verify_chain(path)


@verifies("REQ-PA-004")
def test_reordering_entries_is_detected(pa_audit_log, tmp_path):
    path = _log(pa_audit_log, tmp_path / "log.jsonl")
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n")
    with pytest.raises(pa_audit_log.ChainBrokenError):
        pa_audit_log.verify_chain(path)


@verifies("REQ-PA-004")
def test_a_log_that_does_not_exist_verifies_as_empty(pa_audit_log, tmp_path):
    """Documented behaviour, and the limit of the claim.

    There is nothing to compare a missing file against, so deleting the whole log
    is not detected. The chain covers the entries within a log, not its existence.
    """
    assert pa_audit_log.verify_chain(tmp_path / "does-not-exist.jsonl") == []


@verifies("REQ-PA-004")
def test_blank_lines_in_a_log_are_ignored(pa_audit_log, tmp_path):
    path = _log(pa_audit_log, tmp_path / "log.jsonl", n=2)
    path.write_text(path.read_text().replace("\n", "\n\n"))
    assert [e["case_id"] for e in pa_audit_log.verify_chain(path)] == ["pa-0", "pa-1"]


# --- REQ-PA-005: the auto-finalization gate --------------------------------


def _state(decision, confidence, criteria=(), evidence=()):
    return {
        "determination": {
            "decision": decision,
            "confidence": confidence,
            "rationale": "",
            "gaps": [],
        },
        "criteria": list(criteria),
        "evidence": list(evidence),
    }


def _route(pa_gate, *args, **kwargs):
    return pa_gate.confidence_gate(_state(*args, **kwargs))["route"]


@verifies("REQ-PA-005")
def test_approve_at_or_above_the_threshold_is_finalized_automatically(pa_gate):
    threshold = pa_gate.CONFIDENCE_THRESHOLD
    assert _route(pa_gate, "approve", threshold) == "auto"
    assert _route(pa_gate, "approve", min(1.0, threshold + 0.05)) == "auto"


@verifies("REQ-PA-005")
def test_approve_below_the_threshold_goes_to_a_human(pa_gate):
    assert _route(pa_gate, "approve", pa_gate.CONFIDENCE_THRESHOLD - 0.01) == "hitl"


@verifies("REQ-PA-005")
def test_insufficient_evidence_goes_to_a_human_at_any_confidence(pa_gate):
    assert _route(pa_gate, "insufficient_evidence", 1.0) == "hitl"


REQUIRED = [{"id": "c1", "required": True}]
OPTIONAL = [{"id": "c1", "required": False}]
GAP = [{"criterion_id": "c1", "status": "insufficient"}]


@verifies("REQ-PA-005")
def test_required_insufficient_criterion_forces_review_at_any_confidence(pa_gate):
    assert _route(pa_gate, "approve", 1.0, criteria=REQUIRED, evidence=GAP) == "hitl"


@verifies("REQ-PA-005")
def test_non_required_insufficient_criterion_alone_does_not_force_review(pa_gate):
    assert _route(pa_gate, "approve", 1.0, criteria=OPTIONAL, evidence=GAP) == "auto"
