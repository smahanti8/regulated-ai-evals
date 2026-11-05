"""Structural coverage, scoped to the code that implements a claim.

Repo-wide coverage percentage answers "how much of the code did the suite
touch". It is a useful hygiene metric and it is not a verification argument.
The question IEC 62304 actually asks is narrower and harder: for this specific
claim, have you exercised every path through the code that decides it?

So coverage here is not reported for the repository. It is reported per
declared decision path, and an uncovered branch inside a claim-bearing function
is described as a hole in the argument for that claim, because that is what it
is.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class DecisionPath:
    """A function whose branching decides a claim."""

    id: str
    requirement_ids: tuple[str, ...]
    file: Path
    qualname: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class PathCoverage:
    path_id: str
    requirement_ids: tuple[str, ...]
    location: str
    statements: int
    statements_covered: int
    branches: int
    branches_covered: int
    missing_lines: tuple[int, ...]
    missing_branches: tuple[tuple[int, int], ...]

    @property
    def complete(self) -> bool:
        return (
            self.statements_covered == self.statements
            and self.branches_covered == self.branches
        )

    @property
    def branch_rate(self) -> float:
        return self.branches_covered / self.branches if self.branches else 1.0

    def to_dict(self) -> dict:
        return {
            "path_id": self.path_id,
            "requirement_ids": list(self.requirement_ids),
            "location": self.location,
            "statements": f"{self.statements_covered}/{self.statements}",
            "branches": f"{self.branches_covered}/{self.branches}",
            "branch_rate": round(self.branch_rate, 4),
            "complete": self.complete,
            "missing_lines": list(self.missing_lines),
            "missing_branches": [list(b) for b in self.missing_branches],
        }


class CoverageUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=None)
def _span(file: str, qualname: str) -> tuple[int, int]:
    """First and last line of a qualified name, by parsing the source.

    ast rather than inspect because the target module belongs to the system
    under test and may not be importable in this process — a pinned clone with
    its own dependencies, for instance. Reading the file avoids requiring the
    harness to satisfy the SUT's install.
    """
    tree = ast.parse(Path(file).read_text(encoding="utf-8"))
    parts = qualname.split(".")

    def find(nodes: Sequence[ast.AST], remaining: list[str]) -> ast.AST | None:
        head, rest = remaining[0], remaining[1:]
        for node in nodes:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == head
            ):
                return node if not rest else find(node.body, rest)
        return None

    node = find(tree.body, parts)
    if node is None:
        raise CoverageUnavailable(f"{qualname} not found in {file}")
    return node.lineno, node.end_lineno or node.lineno


def measure(
    coverage_json: Path, paths: Sequence[DecisionPath]
) -> list[PathCoverage]:
    """Intersect a coverage.py JSON report with the declared decision paths."""
    if not coverage_json.exists():
        raise CoverageUnavailable(
            f"No coverage report at {coverage_json}. Run `rae run` first."
        )
    report = json.loads(coverage_json.read_text(encoding="utf-8"))
    by_file = {Path(k).resolve(): v for k, v in report["files"].items()}

    measured: list[PathCoverage] = []
    for path in paths:
        target = path.file.resolve()
        file_report = by_file.get(target)
        if file_report is None:
            raise CoverageUnavailable(
                f"{path.id}: {target} is not in the coverage report. It was never "
                "imported by the suite, so the claim it backs has no structural "
                "evidence at all."
            )
        start, end = _span(str(target), path.qualname)
        in_span = lambda line: start <= line <= end  # noqa: E731

        executed = [l for l in file_report["executed_lines"] if in_span(l)]
        missing = [l for l in file_report["missing_lines"] if in_span(l)]
        missing_branches = [
            (a, b) for a, b in file_report.get("missing_branches", []) if in_span(a)
        ]
        total_branches = _count_branch_exits(str(target), start, end)

        measured.append(
            PathCoverage(
                path_id=path.id,
                requirement_ids=path.requirement_ids,
                location=f"{path.file.name}:{start}-{end} {path.qualname}",
                statements=len(executed) + len(missing),
                statements_covered=len(executed),
                branches=total_branches,
                branches_covered=total_branches - len(missing_branches),
                missing_lines=tuple(missing),
                missing_branches=tuple(missing_branches),
            )
        )
    return measured


def _count_branch_exits(file: str, start: int, end: int) -> int:
    """Number of branch exits in the span.

    Counted from the AST rather than taken from coverage's totals so the
    denominator is the branching in *this function*, not in the file. Each
    if/while contributes two exits (taken and not-taken); each `for` likewise
    (iterated and exhausted).
    """
    tree = ast.parse(Path(file).read_text(encoding="utf-8"))
    exits = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
            continue
        if start <= node.lineno <= end:
            exits += 2
    return exits


def summarise(measured: Sequence[PathCoverage]) -> dict:
    incomplete = [m for m in measured if not m.complete]
    return {
        "decision_paths": len(measured),
        "complete": len(measured) - len(incomplete),
        "incomplete": [m.path_id for m in incomplete],
        "requirements_with_incomplete_paths": sorted(
            {r for m in incomplete for r in m.requirement_ids}
        ),
    }
