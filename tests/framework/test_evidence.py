"""Golden-set integrity, trace capture, and bundle tamper-evidence."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from regulated_ai_evals.bundle import verify as verify_bundle
from regulated_ai_evals.goldens import (
    GoldenProvenance,
    GoldenSet,
    GoldenSetError,
)
from regulated_ai_evals.hashing import canonical_bytes, content_hash
from regulated_ai_evals.trace import Outcome, TestResult, TraceLedger


def provenance(**kw) -> GoldenProvenance:
    return GoldenProvenance(
        derived_from=kw.get("derived_from", "generator"),
        synthetic=kw.get("synthetic", True),
        contains_phi=kw.get("contains_phi", False),
        deidentification=kw.get("deidentification"),
        labelled_by=kw.get("labelled_by", "generator"),
        frozen_on=date(2026, 9, 14),
    )


def golden(records, **kw) -> GoldenSet:
    return GoldenSet(
        id="g",
        version="1.0.0",
        description="d",
        provenance=provenance(**kw),
        records=records,
        label_field="anomaly",
    )


# -- hashing ---------------------------------------------------------------


def test_hash_is_insensitive_to_key_order_and_sensitive_to_values():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 1.0000001})


def test_canonical_bytes_are_stable():
    assert canonical_bytes({"b": [1, 2], "a": "x"}) == b'{"a":"x","b":[1,2]}'


# -- golden sets -----------------------------------------------------------


def test_edited_data_is_caught_by_the_manifest_hash(tmp_path: Path):
    subject = golden([{"v": 1, "anomaly": True}])
    subject._manifest_hash = subject.content_hash
    subject.verify()

    subject.records[0]["v"] = 2
    with pytest.raises(GoldenSetError, match="does not match its manifest"):
        subject.verify()


def test_synthetic_set_containing_an_identifier_shape_is_rejected():
    subject = golden([{"note": "contact 555-12-3456 for details", "anomaly": False}])
    with pytest.raises(GoldenSetError, match="identifier-shaped"):
        subject.verify()


def test_set_cannot_be_synthetic_and_contain_phi():
    with pytest.raises(GoldenSetError, match="synthetic and contains_phi"):
        golden([{"anomaly": False}], contains_phi=True).verify()


def test_real_data_is_not_identifier_scanned():
    """The scan is an attestation check, not a redaction tool.

    Running it on a set that honestly declares itself real would reject the set
    for containing exactly what it says it contains.
    """
    golden([{"dob": "1970-01-01", "anomaly": False}], synthetic=False).verify()


# -- traceability ----------------------------------------------------------


def result(nodeid, outcome, *reqs) -> TestResult:
    return TestResult(nodeid, outcome, 0.01, tuple(reqs))


def test_one_failing_test_withdraws_the_claim():
    ledger = TraceLedger(
        [
            result("t1", Outcome.PASSED, "REQ-1"),
            result("t2", Outcome.FAILED, "REQ-1"),
        ]
    )
    assert ledger.verified("REQ-1") is False


def test_a_claim_with_no_test_is_not_verified():
    assert TraceLedger().verified("REQ-1") is False


def test_orphans_and_unknown_ids_are_distinguished():
    ledger = TraceLedger(
        [
            result("t1", Outcome.PASSED),
            result("t2", Outcome.PASSED, "REQ-TYPO"),
        ]
    )
    assert ledger.orphan_tests() == ["t1"]
    assert ledger.unknown_requirements({"REQ-1"}) == ["REQ-TYPO"]


def test_ledger_round_trips(tmp_path: Path):
    ledger = TraceLedger([result("t1", Outcome.PASSED, "REQ-1")])
    ledger.write(tmp_path / "trace.json")
    assert TraceLedger.read(tmp_path / "trace.json").results == ledger.results


# -- bundle ----------------------------------------------------------------


def seal(tmp_path: Path) -> Path:
    directory = tmp_path / "bundle"
    directory.mkdir()
    (directory / "a.json").write_text('{"x":1}', encoding="utf-8")
    from regulated_ai_evals.hashing import file_hash, write_canonical

    files = {"a.json": file_hash(directory / "a.json")}
    write_canonical(
        directory / "MANIFEST.json",
        {
            "run_id": "r",
            "created": "2026-09-14T00:00:00+00:00",
            "harness_version": "0.1.0",
            "files": files,
            "root_hash": content_hash(files),
        },
    )
    return directory


def test_intact_bundle_verifies(tmp_path: Path):
    assert verify_bundle(seal(tmp_path)) == []


def test_edited_file_is_detected(tmp_path: Path):
    directory = seal(tmp_path)
    (directory / "a.json").write_text('{"x":2}', encoding="utf-8")
    assert "a.json: content does not match the manifest" in verify_bundle(directory)


def test_added_file_is_detected(tmp_path: Path):
    """Slipping an extra document in beside real evidence is the easy attack."""
    directory = seal(tmp_path)
    (directory / "extra.md").write_text("looks official", encoding="utf-8")
    assert any("extra.md" in p for p in verify_bundle(directory))


def test_rewriting_the_manifest_to_match_is_detected(tmp_path: Path):
    """Recomputing a file hash is not enough: the root hash covers the set."""
    directory = seal(tmp_path)
    (directory / "a.json").write_text('{"x":2}', encoding="utf-8")

    from regulated_ai_evals.hashing import file_hash

    manifest = json.loads((directory / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["files"]["a.json"] = file_hash(directory / "a.json")
    (directory / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert "root hash does not match the file hashes it covers" in verify_bundle(
        directory
    )


def test_missing_manifest_is_not_a_bundle(tmp_path: Path):
    assert "not a sealed bundle" in verify_bundle(tmp_path)[0]
