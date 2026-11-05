"""Thresholds and the evidence behind them.

The most common failure in a regulated AI submission is not a bad model. It is
a number — 0.85, 90.0, 5.0 — that appears in the code, appears in the claim,
and has no dataset behind it. Nobody chose it dishonestly; it was a reasonable
first guess that was never revisited, and by the time the claim was written the
number looked like a fact.

This module makes the provenance of every such number explicit, and makes the
absence of provenance a state the system can act on rather than a silence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

import yaml

from .goldens import GoldenSetRef
from .hashing import content_hash


class ThresholdStatus(str, Enum):
    """How the number got there. Ordered weakest to strongest by `rank`."""

    UNCALIBRATED = "uncalibrated"
    """Nobody has said anything. The default, and the honest state for most
    numbers in most systems."""
    ASSERTED = "asserted"
    """A human picked it using judgement. No dataset, no objective function."""
    INHERITED = "inherited"
    """Taken from an external authority: a spec sheet, a standard, a vendor
    limit. Real provenance, but provenance for someone else's operating
    conditions, not evidence about this system's performance."""
    CALIBRATED = "calibrated"
    """Fitted against a named, versioned golden set with a recorded objective
    and a measured operating point."""

    @property
    def rank(self) -> int:
        return _STATUS_RANK[self]


_STATUS_RANK = {
    ThresholdStatus.UNCALIBRATED: 0,
    ThresholdStatus.ASSERTED: 1,
    ThresholdStatus.INHERITED: 2,
    ThresholdStatus.CALIBRATED: 3,
}


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Wilson rather than the normal approximation because the interesting cases
    here are small-n and near the boundary — 3 detections out of 3 — where the
    normal approximation returns a zero-width interval and quietly implies
    certainty that isn't there.
    """
    if total == 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    margin = (
        z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    """Measured performance at this threshold value, with counts kept.

    Counts rather than rates because a rate without its denominator cannot be
    interval-estimated, and an interval is the whole point: a recall of 1.00
    means something very different at n=3 than at n=3000.
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int

    @property
    def positives(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def recall(self) -> float:
        return self.true_positives / self.positives if self.positives else 0.0

    @property
    def recall_ci(self) -> tuple[float, float]:
        return wilson_interval(self.true_positives, self.positives)

    @property
    def recall_ci_width(self) -> float:
        low, high = self.recall_ci
        return high - low

    @property
    def precision(self) -> float:
        flagged = self.true_positives + self.false_positives
        return self.true_positives / flagged if flagged else 0.0

    def to_dict(self) -> dict:
        low, high = self.recall_ci
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "recall": round(self.recall, 4),
            "recall_ci_95": [round(low, 4), round(high, 4)],
            "recall_ci_width": round(self.recall_ci_width, 4),
            "precision": round(self.precision, 4),
        }


@dataclass(frozen=True, slots=True)
class CalibrationEvidence:
    fitted_on: GoldenSetRef
    fitted_value: float
    """The threshold value this operating point was measured at.

    Carried so the gate can check it still matches the value in the source. A
    calibration exercise that concluded 5.4, followed by nobody editing the
    constant, leaves a repository containing genuine evidence for a number the
    system does not use — which reads as calibrated and is not.
    """
    objective: str
    """The thing that was maximised or constrained, in words. A threshold
    fitted without a stated objective was not fitted, it was chosen."""
    operating_point: OperatingPoint
    fitted_date: date
    confirmed_on: GoldenSetRef | None = None
    """Held-out set the operating point was reproduced on. None means the
    number was fitted and measured on the same data."""

    @property
    def in_sample_only(self) -> bool:
        return self.confirmed_on is None

    def to_dict(self) -> dict:
        return {
            "fitted_on": self.fitted_on.to_dict(),
            "confirmed_on": self.confirmed_on.to_dict() if self.confirmed_on else None,
            "fitted_value": self.fitted_value,
            "in_sample_only": self.in_sample_only,
            "objective": self.objective,
            "fitted_date": self.fitted_date.isoformat(),
            "operating_point": self.operating_point.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Threshold:
    """A decision boundary in the system under test, and its provenance."""

    id: str
    value: float
    unit: str
    system: str
    location: str
    """Where the number physically lives, as file:line. An auditor should be
    able to go and look at it."""
    status: ThresholdStatus
    note: str = ""
    source: str = ""
    """For INHERITED: which authority. Empty otherwise."""
    calibration: CalibrationEvidence | None = None

    def __post_init__(self) -> None:
        if self.status is ThresholdStatus.CALIBRATED and self.calibration is None:
            raise ValueError(
                f"{self.id} claims status CALIBRATED with no CalibrationEvidence. "
                "The status is derived from the evidence, not asserted alongside it."
            )
        if self.status is ThresholdStatus.INHERITED and not self.source:
            raise ValueError(
                f"{self.id} claims status INHERITED with no source. Inherited from "
                "where?"
            )

    @property
    def value_hash(self) -> str:
        """Identity of this threshold's current setting.

        A risk acceptance is bound to this hash, so moving the number
        invalidates the sign-off that was granted for the old one.
        """
        return content_hash({"id": self.id, "value": self.value, "unit": self.unit})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "value": self.value,
            "unit": self.unit,
            "system": self.system,
            "location": self.location,
            "status": self.status.value,
            "source": self.source,
            "note": self.note,
            "value_hash": self.value_hash,
            "calibration": self.calibration.to_dict() if self.calibration else None,
        }


@dataclass(frozen=True, slots=True)
class AcceptedNonConformance:
    """A documented, justified, attributed deviation.

    Design controls do not forbid non-conformances. They forbid undocumented
    ones. This type is the difference between the two, and it is why the
    calibration gate can afford to fail by default.
    """

    threshold_id: str
    threshold_value_hash: str
    rationale: str
    accepted_by: str
    accepted_on: str

    def applies_to(self, threshold: Threshold) -> bool:
        return (
            self.threshold_id == threshold.id
            and self.threshold_value_hash == threshold.value_hash
        )

    def to_dict(self) -> dict:
        return {
            "threshold_id": self.threshold_id,
            "threshold_value_hash": self.threshold_value_hash,
            "rationale": self.rationale,
            "accepted_by": self.accepted_by,
            "accepted_on": self.accepted_on,
        }


@dataclass(slots=True)
class RiskAcceptanceLedger:
    """Persisted acceptances, keyed by threshold and bound to its value.

    Stored in the repository rather than passed per-run so that the sign-off is
    reviewable in a diff. An acceptance whose threshold has since moved is
    reported as stale and does not suppress the gate.
    """

    acceptances: list[AcceptedNonConformance] = field(default_factory=list)
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> RiskAcceptanceLedger:
        if not path.exists():
            return cls(path=path)
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            acceptances=[
                AcceptedNonConformance(
                    threshold_id=raw["threshold_id"],
                    threshold_value_hash=raw["threshold_value_hash"],
                    rationale=raw["rationale"],
                    accepted_by=raw["accepted_by"],
                    accepted_on=raw["accepted_on"],
                )
                for raw in document.get("acceptances", [])
            ],
            path=path,
        )

    def find(self, threshold: Threshold) -> AcceptedNonConformance | None:
        for acceptance in self.acceptances:
            if acceptance.applies_to(threshold):
                return acceptance
        return None

    def stale_for(self, threshold: Threshold) -> AcceptedNonConformance | None:
        """An acceptance for this threshold granted against a different value."""
        for acceptance in self.acceptances:
            if acceptance.threshold_id == threshold.id and not acceptance.applies_to(
                threshold
            ):
                return acceptance
        return None

    def accept(
        self, threshold: Threshold, rationale: str, accepted_by: str
    ) -> AcceptedNonConformance:
        acceptance = AcceptedNonConformance(
            threshold_id=threshold.id,
            threshold_value_hash=threshold.value_hash,
            rationale=rationale,
            accepted_by=accepted_by,
            accepted_on=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.acceptances = [
            a for a in self.acceptances if a.threshold_id != threshold.id
        ] + [acceptance]
        return acceptance

    def save(self) -> None:
        if self.path is None:
            raise ValueError("Ledger has no path to save to")
        self.path.write_text(
            yaml.safe_dump(
                {"acceptances": [a.to_dict() for a in self.acceptances]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )


def load_evidence(directory: Path) -> dict[str, CalibrationEvidence]:
    """Read calibration records written by `rae calibrate`.

    Records are files rather than adapter code because calibration is an
    activity with a date and a dataset, not a property of the codebase. The
    record is the artefact the activity produced; deleting it correctly returns
    the threshold to UNCALIBRATED.
    """
    evidence: dict[str, CalibrationEvidence] = {}
    if not directory.exists():
        return evidence

    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        point = raw["operating_point"]
        evidence[raw["threshold_id"]] = CalibrationEvidence(
            fitted_on=_ref(raw["fitted_on"]),
            confirmed_on=_ref(raw["confirmed_on"]) if raw.get("confirmed_on") else None,
            fitted_value=raw["fitted_value"],
            objective=raw["objective"],
            fitted_date=date.fromisoformat(raw["fitted_date"]),
            operating_point=OperatingPoint(
                true_positives=point["true_positives"],
                false_positives=point["false_positives"],
                false_negatives=point["false_negatives"],
                true_negatives=point["true_negatives"],
            ),
        )
    return evidence


def save_evidence(
    directory: Path, threshold_id: str, evidence: CalibrationEvidence
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{threshold_id}.yaml"
    point = evidence.operating_point
    path.write_text(
        yaml.safe_dump(
            {
                "threshold_id": threshold_id,
                "fitted_on": evidence.fitted_on.to_dict(),
                "confirmed_on": (
                    evidence.confirmed_on.to_dict() if evidence.confirmed_on else None
                ),
                "fitted_value": evidence.fitted_value,
                "objective": evidence.objective,
                "fitted_date": evidence.fitted_date.isoformat(),
                "operating_point": {
                    "true_positives": point.true_positives,
                    "false_positives": point.false_positives,
                    "false_negatives": point.false_negatives,
                    "true_negatives": point.true_negatives,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _ref(raw: dict) -> GoldenSetRef:
    return GoldenSetRef(
        id=raw["id"], version=raw["version"], content_hash=raw["content_hash"]
    )
