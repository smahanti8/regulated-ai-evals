"""Fixtures that reach the pinned systems under test.

Nothing here imports from a developer's working copy. Every path goes through
.sut/, which `rae fetch` populated from sut.lock, so a test run is against the
code the bundle will name.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from regulated_ai_evals.adapters import PriorAuthAdapter
from regulated_ai_evals.goldens import load_all

ROOT = Path(__file__).resolve().parents[1]
SUT = ROOT / ".sut"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"{path} not present — run `rae fetch` first", allow_module_level=True)
    return path


@pytest.fixture(scope="session")
def prior_auth_adapter() -> PriorAuthAdapter:
    _require(SUT / "prior-auth-agent")
    return PriorAuthAdapter(SUT / "prior-auth-agent", ROOT / "calibration")


def _prior_auth(module: str):
    _require(SUT / "prior-auth-agent" / "src" / "prior_auth_agent")
    return importlib.import_module(f"prior_auth_agent.{module}")


@pytest.fixture(scope="session")
def pa_validation():
    return _prior_auth("validation")


@pytest.fixture(scope="session")
def pa_audit_log():
    return _prior_auth("audit_log")


@pytest.fixture(scope="session")
def pa_state():
    return _prior_auth("state")


@pytest.fixture(scope="session")
def pa_determination():
    return _prior_auth("nodes.determination")


@pytest.fixture(scope="session")
def pa_gate():
    return _prior_auth("nodes.confidence_gate")


@pytest.fixture(scope="session")
def goldens():
    return load_all(ROOT / "goldens")


@pytest.fixture(scope="session")
def terminology():
    _require(SUT / "surgical-fhir-pipeline" / "src" / "surgical_fhir")
    from surgical_fhir import terminology as tx

    return tx


@pytest.fixture(scope="session")
def trust():
    _require(SUT / "surgical-fhir-pipeline" / "src" / "surgical_fhir")
    from surgical_fhir import trust_status

    return trust_status
