"""pytest plugin: capture the traceability link at execution time.

Registered as a pytest11 entry point, so `@verifies(...)` works in any suite
that has this package installed. The ledger is written on session finish to the
path given by --rae-trace; `rae run` passes that path and reads it back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .trace import Outcome, TestResult, TraceLedger

_LEDGER_KEY = "_rae_ledger"


def verifies(*requirement_ids: str):
    """Declare which requirements a test provides evidence for.

        @verifies("REQ-TX-003")
        def test_provisional_binding_is_not_trusted(): ...

    Ids are not validated here — an unknown id is a finding rather than a
    collection error, and `rae run` reports it as one. Failing at import time
    would mean a register typo stops the suite from running at all, which
    destroys the evidence you were trying to collect.
    """
    return pytest.mark.verifies(*requirement_ids)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--rae-trace",
        action="store",
        default=None,
        metavar="PATH",
        help="Write the requirement traceability ledger to PATH as JSON.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "verifies(*req_ids): declares which requirements this test provides "
        "evidence for",
    )
    setattr(config, _LEDGER_KEY, TraceLedger())


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record one result per test, from whichever phase decided its fate.

    A test that errors in setup never reaches the call phase, and silently
    dropping it would leave its requirement looking merely unclaimed rather
    than broken.
    """
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _pending.append(report)


_pending: list[pytest.TestReport] = []


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    ledger: TraceLedger = getattr(config, _LEDGER_KEY, None) or TraceLedger()

    marks = _collect_marks(session)
    for report in _pending:
        ledger.add(
            TestResult(
                nodeid=report.nodeid,
                outcome=_outcome(report),
                duration_s=report.duration,
                requirement_ids=marks.get(report.nodeid, ()),
                message=_message(report),
            )
        )
    _pending.clear()

    destination = config.getoption("--rae-trace")
    if destination:
        ledger.write(Path(destination))


def _collect_marks(session: pytest.Session) -> dict[str, tuple[str, ...]]:
    marks: dict[str, tuple[str, ...]] = {}
    for item in session.items:
        ids: list[str] = []
        for mark in item.iter_markers(name="verifies"):
            ids.extend(mark.args)
        marks[item.nodeid] = tuple(dict.fromkeys(ids))
    return marks


def _outcome(report: pytest.TestReport) -> Outcome:
    if report.when == "setup" and report.outcome == "failed":
        return Outcome.ERROR
    return {
        "passed": Outcome.PASSED,
        "failed": Outcome.FAILED,
        "skipped": Outcome.SKIPPED,
    }[report.outcome]


def _message(report: pytest.TestReport) -> str:
    if report.outcome == "passed":
        return ""
    text = str(report.longrepr) if report.longrepr else ""
    return text.strip().splitlines()[-1][:300] if text else ""
