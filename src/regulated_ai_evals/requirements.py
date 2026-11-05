"""The claim register.

A requirement here is not a feature description. It is a claim you intend to
make about the system to someone who can stop you shipping. Everything else in
the framework attaches to one of these; nothing is measured that no one claimed.

The acceptance criterion is a field rather than a docstring on the test because
it has to be written before the test exists. A pass condition authored after
seeing the result is not a pass condition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml


class RiskClass(str, Enum):
    """How much of the decision the system is actually making.

    Graded by the consequence of the claim being wrong, not by the technology.
    This is the axis the calibration gate keys off: DECISION_DRIVING claims
    cannot rest on thresholds nobody calibrated.
    """

    INFORMATIONAL = "informational"
    """A human reads the output and decides independently."""
    SUPPORTIVE = "supportive"
    """Drives a decision that a human confirms with the evidence in front of them."""
    DECISION_DRIVING = "decision_driving"
    """The system acts, or a human will not realistically second-guess it."""


class VerificationMethod(str, Enum):
    TEST = "test"
    ANALYSIS = "analysis"
    INSPECTION = "inspection"
    DEMONSTRATION = "demonstration"


class Scope(str, Enum):
    """Whether this run undertook to verify the claim at all.

    Distinguishing "we tried and have no evidence" from "we did not undertake
    this" is the difference between a gap and a boundary. An auditor needs both
    stated, and needs them stated differently.
    """

    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class Requirement:
    id: str
    statement: str
    rationale: str
    risk_class: RiskClass
    verification: VerificationMethod
    acceptance: str
    system: str
    behavioural_statement: str = ""
    """What is still true if the performance claim cannot be supported. Written
    at the same time as the claim, by the same person, so the fallback is not
    drafted under pressure once the gate has already failed."""
    scope: Scope = Scope.IN_SCOPE
    scope_note: str = ""
    thresholds: tuple[str, ...] = ()
    parent: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "statement": self.statement,
            "behavioural_statement": self.behavioural_statement,
            "rationale": self.rationale,
            "risk_class": self.risk_class.value,
            "verification": self.verification.value,
            "acceptance": self.acceptance,
            "system": self.system,
            "scope": self.scope.value,
            "scope_note": self.scope_note,
            "thresholds": list(self.thresholds),
            "parent": self.parent,
        }


class RegisterError(ValueError):
    """Raised for a register that cannot be trusted to drive a run."""


@dataclass(slots=True)
class RequirementRegister:
    requirements: dict[str, Requirement] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path) -> RequirementRegister:
        register = cls()
        for path in sorted(directory.glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            system = document.get("system") or path.stem
            for raw in document.get("requirements", []):
                requirement = _parse(raw, system=system, source=path)
                if requirement.id in register.requirements:
                    raise RegisterError(
                        f"Duplicate requirement id {requirement.id!r} in {path.name}"
                    )
                register.requirements[requirement.id] = requirement
        register.validate()
        return register

    def validate(self) -> None:
        for requirement in self.requirements.values():
            if requirement.parent and requirement.parent not in self.requirements:
                raise RegisterError(
                    f"{requirement.id} declares parent {requirement.parent!r}, "
                    "which is not in the register"
                )

    def in_scope(self) -> list[Requirement]:
        return [r for r in self.ordered() if r.scope is Scope.IN_SCOPE]

    def ordered(self) -> list[Requirement]:
        return [self.requirements[k] for k in sorted(self.requirements)]

    def for_system(self, system: str) -> list[Requirement]:
        return [r for r in self.ordered() if r.system == system]

    def threshold_ids(self) -> set[str]:
        return {t for r in self.requirements.values() for t in r.thresholds}

    def __getitem__(self, requirement_id: str) -> Requirement:
        return self.requirements[requirement_id]

    def __contains__(self, requirement_id: object) -> bool:
        return requirement_id in self.requirements

    def __len__(self) -> int:
        return len(self.requirements)


def _parse(raw: dict, system: str, source: Path) -> Requirement:
    missing = {"id", "statement", "rationale", "risk_class", "acceptance"} - raw.keys()
    if missing:
        raise RegisterError(
            f"Requirement in {source.name} missing {sorted(missing)}: {raw.get('id', raw)!r}"
        )
    return Requirement(
        id=raw["id"],
        statement=raw["statement"].strip(),
        rationale=raw["rationale"].strip(),
        risk_class=RiskClass(raw["risk_class"]),
        verification=VerificationMethod(raw.get("verification", "test")),
        acceptance=raw["acceptance"].strip(),
        system=raw.get("system", system),
        behavioural_statement=raw.get("behavioural_statement", "").strip(),
        scope=Scope(raw.get("scope", "in_scope")),
        scope_note=raw.get("scope_note", "").strip(),
        thresholds=tuple(raw.get("thresholds", ())),
        parent=raw.get("parent"),
    )
