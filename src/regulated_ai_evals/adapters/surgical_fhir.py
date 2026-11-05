"""Adapter: surgical telemetry to FHIR R4B, scoped to terminology trust.

This run verifies the binding-trust layer only — `trust_status.py` and
`terminology.py`. The mapping, quality and API layers exist and are tested in
their own repository; they are declared out of scope here rather than left
unmentioned, because "we did not undertake this" and "we tried and failed" look
identical in a matrix that only records passes.

Its safety comes
from a categorical refusal — `UnmappedConceptError` — rather than from a
numeric boundary, so most of its claims verify without any calibration at all.
The one claim that does need a boundary is the one that has no boundary behind
it, and the gate says so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..calibration import Threshold, ThresholdStatus
from ..identity import SUTIdentity, git_identity
from ..structural import DecisionPath

SYSTEM = "surgical-fhir"

REPO = "https://github.com/smahanti8/surgical-fhir-pipeline"


class SurgicalFHIRAdapter:
    name = "surgical-fhir-pipeline"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.package = root / "src" / "surgical_fhir"

    def identity(self) -> SUTIdentity:
        return git_identity(self.root, name=self.name, source=REPO)

    def thresholds(self) -> Sequence[Threshold]:
        return [
            Threshold(
                id="THR-FHIR-PROVISIONAL-CEILING",
                value=0.0,
                unit="fraction of bindings",
                system=SYSTEM,
                location="not present in source",
                status=ThresholdStatus.UNCALIBRATED,
                note=(
                    "No ceiling exists. `coverage_report()` measures the "
                    "verified/provisional split and publishes it; nothing consumes "
                    "the number to gate anything. That is a defensible design — "
                    "reporting without gating is honest — but it means any claim "
                    "that the concept map is fit for clinical exchange has no "
                    "decision boundary behind it. Recorded as a threshold with no "
                    "implementation so the absence is visible rather than inferred."
                ),
            )
        ]

    def decision_paths(self) -> Sequence[DecisionPath]:
        terminology = self.package / "terminology.py"
        trust = self.package / "trust_status.py"
        return [
            DecisionPath(
                id="DP-FHIR-IS-TRUSTED",
                requirement_ids=("REQ-TX-001",),
                file=trust,
                qualname="Binding.is_trusted",
                note="VERIFIED is the only trusted state. No implicit promotion.",
            ),
            DecisionPath(
                id="DP-FHIR-PROCEDURE-BINDING",
                requirement_ids=("REQ-TX-002",),
                file=terminology,
                qualname="procedure_binding",
                note="Refuse-on-unknown rather than emit an uncoded concept.",
            ),
            DecisionPath(
                id="DP-FHIR-OBSERVATION-BINDING",
                requirement_ids=("REQ-TX-002",),
                file=terminology,
                qualname="observation_binding",
            ),
            DecisionPath(
                id="DP-FHIR-UCUM-UNIT",
                requirement_ids=("REQ-TX-002",),
                file=terminology,
                qualname="ucum_unit",
            ),
            DecisionPath(
                id="DP-FHIR-GENDER",
                requirement_ids=("REQ-TX-004",),
                file=terminology,
                qualname="administrative_gender",
                note=(
                    "The one function in the module that degrades instead of "
                    "refusing: unknown input returns 'unknown'. Declared as its own "
                    "decision path so the exception to the fail-loud rule is "
                    "verified deliberately rather than noticed later."
                ),
            ),
            DecisionPath(
                id="DP-FHIR-COVERAGE-REPORT",
                requirement_ids=("REQ-TX-003", "REQ-TX-005"),
                file=terminology,
                qualname="coverage_report",
            ),
        ]
