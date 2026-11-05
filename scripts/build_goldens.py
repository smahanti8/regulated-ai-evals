"""Build the golden set for the confidence-threshold calibration.

goldens/prior-auth-determinations-v1 is derived, not authored: each row pairs a
determination drafted by the pinned prior-auth-agent (recorded model output)
with the decision its own golden fixture says is correct. Nothing here is typed
by hand, and the script refuses to run against a checkout that is not the pin in
sut.lock, so the recorded provenance cannot describe code the data did not come
from.

The labels are NOT independent. They come from the fixtures of the system under
test, written by the same author, so this set can show how the confidence gate
behaves on that system's own cases; it cannot show that those cases are the right
ones. The manifest says so.

Run `rae fetch` first. Deterministic: same pinned checkout, same bytes.
"""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import date
from pathlib import Path

import yaml

from regulated_ai_evals.goldens import GoldenSet
from regulated_ai_evals.hashing import content_hash, file_hash
from regulated_ai_evals.sut import load_lock

ROOT = Path(__file__).resolve().parents[1]
SUT = ROOT / ".sut" / "prior-auth-agent"
GOLDENS = ROOT / "goldens"
SET_ID = "prior-auth-determinations-v1"
COLUMNS = ["case_id", "decision", "confidence", "expected_decision", "correct", "wrong_approve"]


def pinned_sha() -> str:
    pin = next(s.pin for s in load_lock(ROOT / "sut.lock") if s.name == "prior-auth-agent")
    head = subprocess.run(
        ["git", "-C", str(SUT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if head != pin:
        raise SystemExit(f"{SUT} is at {head[:12]} but sut.lock pins {pin[:12]}. Run `rae fetch`.")
    return pin


def rows() -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    recorded_on: list[str] = []
    for fixture in sorted((SUT / "evals" / "golden" / "cases").glob("case_*.yaml")):
        case = yaml.safe_load(fixture.read_text(encoding="utf-8"))
        expected = ((case.get("ground_truth") or {}).get("outcome") or {}).get("decision")
        cassette = SUT / "evals" / "recorded" / f"{case['id']}.json"
        if not expected or not cassette.exists():
            continue  # rejected at intake/eligibility: no drafter output to score
        recording = json.loads(cassette.read_text(encoding="utf-8"))
        drafter = next(
            (n for name, n in recording["nodes"].items() if "determination" in name), None
        )
        if drafter is None:
            continue
        response = drafter["response"]
        recorded_on.append(recording["recorded_at"][:10])
        decision = response["decision"]
        out.append(
            {
                "case_id": case["id"],
                "decision": decision,
                "confidence": f"{float(response['confidence']):.2f}",
                "expected_decision": expected,
                "correct": str(decision == expected).lower(),
                "wrong_approve": str(decision == "approve" and expected != "approve").lower(),
            }
        )
    return out, recorded_on


def main() -> None:
    sha = pinned_sha()
    data, recorded_on = rows()
    directory = GOLDENS / SET_ID
    directory.mkdir(parents=True, exist_ok=True)
    data_path = directory / "data.csv"
    with data_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(data)

    manifest = {
        "id": SET_ID,
        "version": "1.0.0",
        "description": (
            "Determinations drafted by prior-auth-agent on its own golden cases, with "
            "the decision each case's fixture says is correct."
        ),
        "data_file": "data.csv",
        "data_file_hash": file_hash(data_path),
        "label_field": "wrong_approve",
        "provenance": {
            "derived_from": (
                f"prior-auth-agent@{sha}: evals/recorded/*.json (recorded model output, "
                f"{min(recorded_on)} to {max(recorded_on)}) and evals/golden/cases/*.yaml "
                "(ground_truth), via scripts/build_goldens.py"
            ),
            "synthetic": True,
            "contains_phi": False,
            "deidentification": None,
            "labelled_by": (
                "the system's own golden fixtures, written by the same author as the "
                "system under test: NOT independent of it. Decisions and confidences are "
                "recorded model output, not fabricated"
            ),
            "frozen_on": date.today().isoformat(),
        },
        "content_hash": "",
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    loaded = GoldenSet.load(directory)
    manifest["content_hash"] = content_hash({"id": loaded.id, "records": loaded.records})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    approvals = sum(1 for r in loaded.records if r["decision"] == "approve")
    print(
        f"{SET_ID}@1.0.0: {len(loaded.records)} rows, {approvals} approvals, "
        f"{loaded.positives} wrong approvals, {manifest['content_hash'][:23]}…"
    )


if __name__ == "__main__":
    main()
