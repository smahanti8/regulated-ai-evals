"""Adapter: prior-authorization agent.

Most of this system's safety comes from categorical refusals: a `met` claim
without a quote and a citation is rejected, an unresolvable citation is stripped,
the drafter cannot emit a denial, a tampered decision log is detected. None of
those needs a calibrated number, so they verify cleanly.

The claim that does need one is the auto-finalization gate. The threshold behind
it, 0.85, is a round number with no derivation in the repository; its own
decision log calls it uncalibrated. It is also read from the environment, so
what the source pins is a default, not necessarily the value a deployment runs.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Sequence

from ..calibration import (
    OperatingPoint,
    Threshold,
    ThresholdStatus,
    load_evidence,
)
from ..identity import SUTIdentity, git_identity
from ..structural import DecisionPath
from .base import read_env_default

SYSTEM = "prior-auth-agent"

REPO = "https://github.com/smahanti8/prior-auth-agent"

THRESHOLD_ID = "THR-CONFIDENCE"


def _cell(flagged: bool, actual: bool) -> str:
    if flagged and actual:
        return "tp"
    if flagged:
        return "fp"
    return "fn" if actual else "tn"


class PriorAuthAdapter:
    name = SYSTEM

    def __init__(self, root: Path, calibration_dir: Path) -> None:
        self.root = root
        self.package = root / "src" / "prior_auth_agent"
        self.calibration_dir = calibration_dir

    def identity(self) -> SUTIdentity:
        return git_identity(self.root, name=self.name, source=REPO)

    def thresholds(self) -> Sequence[Threshold]:
        value, line, variable = read_env_default(
            self.package / "config.py", "CONFIDENCE_THRESHOLD"
        )
        calibration = load_evidence(self.calibration_dir).get(THRESHOLD_ID)
        return [
            Threshold(
                id=THRESHOLD_ID,
                value=value,
                unit="confidence (0-1)",
                system=SYSTEM,
                location=f"config.py:{line}",
                status=(
                    ThresholdStatus.CALIBRATED if calibration else ThresholdStatus.ASSERTED
                ),
                note=(
                    "Auto-finalization requires confidence at or above this value. "
                    "The repository's decision log (D3) says a fixed 0.85 is "
                    "uncalibrated and plausibly too strict or too lax; nothing "
                    "derives it. The source pins the default only: it is read from "
                    f"the {variable} environment variable, so a deployment that "
                    "sets it runs a value this evidence does not describe."
                ),
                calibration=calibration,
            )
        ]

    def measure(
        self, threshold_id: str, records: Sequence[dict], label_field: str
    ) -> OperatingPoint:
        """Replay the system's own gate over recorded drafts and count outcomes.

        Only approval drafts are measured, because the threshold governs nothing
        else: a non-approval goes to review at any confidence. A positive is a
        wrong approval, and a flag is the gate keeping it out of automatic
        finalization. The gate is called with no criteria, so this measures the
        confidence rule in isolation; the required-criterion rule is verified
        separately.
        """
        if threshold_id != THRESHOLD_ID:
            raise KeyError(threshold_id)
        gate = self._gate()
        counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for record in records:
            if record["decision"] != "approve":
                continue
            state = {
                "determination": {
                    "decision": "approve",
                    "confidence": float(record["confidence"]),
                    "rationale": "",
                    "gaps": [],
                },
                "criteria": [],
                "evidence": [],
            }
            flagged = gate.confidence_gate(state)["route"] == "hitl"
            counts[_cell(flagged, bool(record[label_field]))] += 1
        return OperatingPoint(
            true_positives=counts["tp"],
            false_positives=counts["fp"],
            false_negatives=counts["fn"],
            true_negatives=counts["tn"],
        )

    def _gate(self):
        source = str(self.root / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        return importlib.import_module("prior_auth_agent.nodes.confidence_gate")

    def decision_paths(self) -> Sequence[DecisionPath]:
        validation = self.package / "validation.py"
        audit_log = self.package / "audit_log.py"
        gate = self.package / "nodes" / "confidence_gate.py"
        return [
            DecisionPath(
                id="DP-PA-CITATION-PRESENCE",
                requirement_ids=("REQ-PA-001",),
                file=validation,
                qualname="EvidenceClaim._citation_or_no_claim",
                note="A met claim without a quote or a citation is refused.",
            ),
            DecisionPath(
                id="DP-PA-CITATION-RESOLVE",
                requirement_ids=("REQ-PA-002",),
                file=validation,
                qualname="resolve_citations",
                note="Strip what does not resolve; downgrade when nothing survives.",
            ),
            DecisionPath(
                id="DP-PA-GATE",
                requirement_ids=("REQ-PA-005",),
                file=gate,
                qualname="confidence_gate",
                note="The auto-finalization decision.",
            ),
            DecisionPath(
                id="DP-PA-CHAIN-APPEND",
                requirement_ids=("REQ-PA-004",),
                file=audit_log,
                qualname="append_chained",
            ),
            DecisionPath(
                id="DP-PA-CHAIN-VERIFY",
                requirement_ids=("REQ-PA-004",),
                file=audit_log,
                qualname="verify_chain",
            ),
        ]
