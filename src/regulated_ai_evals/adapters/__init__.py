"""Adapters: one per system under test."""

from __future__ import annotations

from pathlib import Path

from .prior_auth import PriorAuthAdapter
from .surgical_fhir import SurgicalFHIRAdapter

__all__ = ["PriorAuthAdapter", "SurgicalFHIRAdapter", "build_all"]


def build_all(sut_dir: Path, calibration_dir: Path) -> list:
    """Every adapter, pointed at its pinned checkout under `sut_dir`.

    An adapter is built whether or not its system has been fetched. Asking it
    for thresholds is what fails when the system is absent, and the caller
    reports that instead of crashing.
    """
    return [
        SurgicalFHIRAdapter(sut_dir / "surgical-fhir-pipeline"),
        PriorAuthAdapter(sut_dir / "prior-auth-agent", calibration_dir),
    ]
