"""Requirement-to-test traceability.

The matrix is captured while the tests run, not reconstructed from them
afterwards. That is the entire design: a report generator that walks the tree
and infers which test covers which requirement produces the same CSV and proves
nothing, because the inference is the part that can be wrong. Here the
requirement id has to be present in the source at the moment the assertion
executes, or no link is recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Outcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TestResult:
    __test__ = False  # not a pytest test class, despite the name

    nodeid: str
    outcome: Outcome
    duration_s: float
    requirement_ids: tuple[str, ...]
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "nodeid": self.nodeid,
            "outcome": self.outcome.value,
            "duration_s": round(self.duration_s, 4),
            "requirement_ids": list(self.requirement_ids),
            "message": self.message,
        }


@dataclass(slots=True)
class TraceLedger:
    results: list[TestResult] = field(default_factory=list)

    def add(self, result: TestResult) -> None:
        self.results.append(result)

    def forward(self) -> dict[str, list[TestResult]]:
        """requirement -> the tests that claim to provide evidence for it."""
        index: dict[str, list[TestResult]] = {}
        for result in self.results:
            for requirement_id in result.requirement_ids:
                index.setdefault(requirement_id, []).append(result)
        return index

    def verified(self, requirement_id: str) -> bool:
        """A requirement is verified when at least one test claims it and every
        test that claims it passed. One failing test is enough to withdraw the
        claim; a passing sibling does not compensate for it."""
        results = self.forward().get(requirement_id, [])
        return bool(results) and all(r.outcome is Outcome.PASSED for r in results)

    def verification_map(self, requirement_ids: list[str]) -> dict[str, bool]:
        return {rid: self.verified(rid) for rid in requirement_ids}

    def unverified(self, requirement_ids: list[str]) -> list[str]:
        return [rid for rid in requirement_ids if not self.verified(rid)]

    def orphan_tests(self) -> list[str]:
        """Tests that declare no requirement.

        Reported, never fatal. Exploratory and regression tests are legitimate;
        the point of surfacing them is that a suite drifting towards mostly
        orphans is a suite that has stopped tracking what the product claims.
        """
        return [r.nodeid for r in self.results if not r.requirement_ids]

    def unknown_requirements(self, known: set[str]) -> list[str]:
        """Ids cited by a test that do not exist in the register — a typo, or a
        claim deleted while its test survived."""
        cited = {rid for r in self.results for rid in r.requirement_ids}
        return sorted(cited - known)

    def to_dict(self) -> dict:
        return {"results": [r.to_dict() for r in self.results]}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> TraceLedger:
        document = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            results=[
                TestResult(
                    nodeid=r["nodeid"],
                    outcome=Outcome(r["outcome"]),
                    duration_s=r["duration_s"],
                    requirement_ids=tuple(r["requirement_ids"]),
                    message=r.get("message", ""),
                )
                for r in document["results"]
            ]
        )
