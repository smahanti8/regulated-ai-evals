"""The evidence bundle: one sealed directory an auditor can actually read.

Two properties matter more than the contents.

Tamper-evidence. MANIFEST.json holds a hash per file plus a root hash over
those. `rae verify` recomputes both. This is not a signature and does not claim
to be — it detects accidental drift and casual editing, which is the realistic
threat, without requiring a PKI nobody will stand up.

Exceptions first. SUMMARY.md opens with what this bundle does *not* support:
unverified claims, uncalibrated thresholds, accepted non-conformances,
incomplete decision paths. A summary that opens with a pass count trains the
reader to stop at the pass count.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .calibration import Threshold, ThresholdStatus
from .claims import ClaimStrength, ClaimVerdict, effective_status
from .goldens import GoldenSet
from .hashing import content_hash, file_hash, write_canonical
from .identity import RunRecord
from .requirements import RequirementRegister, Scope
from .structural import PathCoverage, summarise
from .trace import Outcome, TraceLedger

MANIFEST = "MANIFEST.json"


@dataclass(slots=True)
class Bundle:
    run: RunRecord
    register: RequirementRegister
    ledger: TraceLedger
    thresholds: dict[str, Threshold]
    verdicts: list[ClaimVerdict]
    goldens: dict[str, GoldenSet]
    coverage: list[PathCoverage]
    sources: list[dict]

    def write(self, root: Path) -> Path:
        directory = root / self.run.run_id
        directory.mkdir(parents=True, exist_ok=True)

        hashes: dict[str, str] = {}
        hashes["run.json"] = write_canonical(
            directory / "run.json", {**self.run.to_dict(), "sources": self.sources}
        )
        hashes["requirements.json"] = write_canonical(
            directory / "requirements.json",
            {"requirements": [r.to_dict() for r in self.register.ordered()]},
        )
        hashes["results.json"] = write_canonical(
            directory / "results.json", self.ledger.to_dict()
        )
        hashes["thresholds.json"] = write_canonical(
            directory / "thresholds.json",
            {"thresholds": [self._threshold_record(t) for t in self._ordered_thresholds()]},
        )
        hashes["claims.json"] = write_canonical(
            directory / "claims.json", {"claims": [v.to_dict() for v in self.verdicts]}
        )
        hashes["goldens.json"] = write_canonical(
            directory / "goldens.json",
            {"golden_sets": [g.to_dict() for g in self.goldens.values()]},
        )
        hashes["coverage.json"] = write_canonical(
            directory / "coverage.json",
            {
                "summary": summarise(self.coverage),
                "decision_paths": [c.to_dict() for c in self.coverage],
            },
        )
        hashes["nonconformances.json"] = write_canonical(
            directory / "nonconformances.json",
            {"accepted": [self._acceptance_record(v) for v in self._accepted()]},
        )

        (directory / "traceability.csv").write_text(
            self._traceability_csv(), encoding="utf-8", newline=""
        )
        hashes["traceability.csv"] = file_hash(directory / "traceability.csv")

        (directory / "SUMMARY.md").write_text(self._summary(), encoding="utf-8")
        hashes["SUMMARY.md"] = file_hash(directory / "SUMMARY.md")

        write_canonical(
            directory / MANIFEST,
            {
                "run_id": self.run.run_id,
                "created": self.run.started_at,
                "harness_version": self.run.environment.harness_version,
                "files": hashes,
                "root_hash": content_hash(hashes),
            },
        )
        return directory

    # -- sections ----------------------------------------------------------

    def _ordered_thresholds(self) -> list[Threshold]:
        return [self.thresholds[k] for k in sorted(self.thresholds)]

    def _threshold_record(self, threshold: Threshold) -> dict:
        """Declared status alongside the status the evidence actually supports.

        Recording only the declared status would put "calibrated" in this table
        for a threshold the gate is treating as asserted, and leave the reader
        to reconcile two sections that disagree.
        """
        status, demotions = effective_status(threshold)
        return {
            **threshold.to_dict(),
            "declared_status": threshold.status.value,
            "effective_status": status.value,
            "demotions": demotions,
        }

    def _accepted(self) -> list[ClaimVerdict]:
        return [v for v in self.verdicts if v.acceptance is not None]

    def _acceptance_record(self, verdict: ClaimVerdict) -> dict:
        assert verdict.acceptance is not None
        return {
            "requirement_id": verdict.requirement_id,
            "risk_class": verdict.risk_class.value,
            "claimed": verdict.claimed,
            "supportable": verdict.supportable,
            **verdict.acceptance.to_dict(),
        }

    def _traceability_csv(self) -> str:
        forward = self.ledger.forward()
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "requirement_id",
                "system",
                "risk_class",
                "scope",
                "statement",
                "acceptance_criterion",
                "verification",
                "test_nodeid",
                "outcome",
                "claim_strength",
                "supportable_claim",
            ]
        )
        for requirement in self.register.ordered():
            verdict = next(
                (v for v in self.verdicts if v.requirement_id == requirement.id), None
            )
            strength = verdict.strength.value if verdict else "not_evaluated"
            supportable = verdict.supportable if verdict else requirement.scope_note
            results = forward.get(requirement.id, [])
            if not results:
                writer.writerow(
                    [
                        requirement.id,
                        requirement.system,
                        requirement.risk_class.value,
                        requirement.scope.value,
                        requirement.statement,
                        requirement.acceptance,
                        requirement.verification.value,
                        "",
                        "NO EVIDENCE"
                        if requirement.scope is Scope.IN_SCOPE
                        else "OUT OF SCOPE",
                        strength,
                        supportable,
                    ]
                )
                continue
            for result in results:
                writer.writerow(
                    [
                        requirement.id,
                        requirement.system,
                        requirement.risk_class.value,
                        requirement.scope.value,
                        requirement.statement,
                        requirement.acceptance,
                        requirement.verification.value,
                        result.nodeid,
                        result.outcome.value,
                        strength,
                        supportable,
                    ]
                )
        return buffer.getvalue()

    def _summary(self) -> str:
        out: list[str] = []
        w = out.append

        in_scope = self.register.in_scope()
        unverified = self.ledger.unverified([r.id for r in in_scope])
        uncalibrated = [
            t
            for t in self._ordered_thresholds()
            if effective_status(t)[0] is not ThresholdStatus.CALIBRATED
        ]
        downgraded = [v for v in self.verdicts if v.strength is not ClaimStrength.PERFORMANCE]
        accepted = self._accepted()
        incomplete = [c for c in self.coverage if not c.complete]
        failures = [r for r in self.ledger.results if r.outcome is not Outcome.PASSED]

        w(f"# Evidence bundle {self.run.run_id}")
        w("")
        w(f"Generated {self.run.started_at} by regulated-ai-evals "
          f"{self.run.environment.harness_version}.")
        w("")
        w("## 1. What this bundle does not support")
        w("")
        w("Read this section first. Everything below it is the supporting detail.")
        w("")

        if not any([unverified, downgraded, accepted, incomplete, failures]):
            w("Nothing. Every in-scope claim is verified and every threshold it "
              "rests on is calibrated.")
        else:
            if downgraded:
                w(f"**{len(downgraded)} claim(s) reduced to what the evidence supports.**")
                w("")
                for verdict in downgraded:
                    w(f"- `{verdict.requirement_id}` "
                      f"({verdict.risk_class.value}, now *{verdict.strength.value}*)")
                    w(f"  - claimed: {verdict.claimed}")
                    w(f"  - supportable: {verdict.supportable}")
                    for reason in verdict.reasons:
                        w(f"  - because: {reason}")
                w("")
            if accepted:
                w(f"**{len(accepted)} accepted non-conformance(s).** These did not "
                  "block the run because someone signed for them.")
                w("")
                for verdict in accepted:
                    acceptance = verdict.acceptance
                    assert acceptance is not None
                    w(f"- `{verdict.requirement_id}` / `{acceptance.threshold_id}` "
                      f"— accepted by **{acceptance.accepted_by}** on "
                      f"{acceptance.accepted_on}")
                    w(f"  - rationale: {acceptance.rationale}")
                w("")
            if unverified:
                w(f"**{len(unverified)} in-scope claim(s) with no passing evidence:** "
                  + ", ".join(f"`{r}`" for r in unverified))
                w("")
            if failures:
                w(f"**{len(failures)} failing or skipped test(s):**")
                w("")
                for result in failures:
                    w(f"- `{result.nodeid}` — {result.outcome.value}"
                      + (f": {result.message}" if result.message else ""))
                w("")
            if incomplete:
                w(f"**{len(incomplete)} decision path(s) not fully exercised.** An "
                  "unexercised branch inside a claim-bearing function is a hole in "
                  "the argument for that claim.")
                w("")
                for path in incomplete:
                    w(f"- `{path.path_id}` ({path.location}) — branches "
                      f"{path.branches_covered}/{path.branches}, statements "
                      f"{path.statements_covered}/{path.statements}; backs "
                      + ", ".join(f"`{r}`" for r in path.requirement_ids))
                w("")

        out_of_scope = [
            r for r in self.register.ordered() if r.scope is Scope.OUT_OF_SCOPE
        ]
        if out_of_scope:
            w("## 2. Declared out of scope for this run")
            w("")
            w("Not gaps. Claims this run did not undertake to verify. The "
              "distinction is deliberate: a boundary is a decision, a gap is a "
              "defect, and an auditor needs to be told which is which.")
            w("")
            for requirement in out_of_scope:
                w(f"- `{requirement.id}` — {requirement.statement}")
                if requirement.scope_note:
                    w(f"  - {requirement.scope_note}")
            w("")

        w("## 3. Systems under test")
        w("")
        w("| system | kind | pinned at |")
        w("| --- | --- | --- |")
        for source in self.sources:
            w(f"| {source['name']} | {source['kind']} | `{source['pin'][:19]}` |")
        w("")

        w("## 4. Claims")
        w("")
        w("| requirement | risk class | scope | evidence | claim supported |")
        w("| --- | --- | --- | --- | --- |")
        forward = self.ledger.forward()
        for requirement in self.register.ordered():
            verdict = next(
                (v for v in self.verdicts if v.requirement_id == requirement.id), None
            )
            if requirement.scope is Scope.OUT_OF_SCOPE:
                evidence, strength = "not undertaken", "—"
            else:
                results = forward.get(requirement.id, [])
                evidence = (
                    f"{len(results)} test(s), "
                    + ("all passing" if self.ledger.verified(requirement.id) else "NOT PASSING")
                    if results
                    else "**none**"
                )
                strength = verdict.strength.value if verdict else "—"
            w(f"| `{requirement.id}` | {requirement.risk_class.value} | "
              f"{requirement.scope.value} | {evidence} | {strength} |")
        w("")

        w("## 5. Thresholds")
        w("")
        w("Declared status is what the repository asserts. Effective status is what "
          "the evidence supports, and it is the one the gate uses.")
        w("")
        w("| threshold | value | declared | effective | backs | evidence |")
        w("| --- | --- | --- | --- | --- | --- |")
        for threshold in self._ordered_thresholds():
            backing = [
                r.id for r in self.register.ordered() if threshold.id in r.thresholds
            ]
            status, demotions = effective_status(threshold)
            if threshold.calibration:
                point = threshold.calibration.operating_point
                low, high = point.recall_ci
                evidence = (
                    f"{threshold.calibration.fitted_on}, recall {point.recall:.2f} "
                    f"CI [{low:.2f}, {high:.2f}], n={point.positives}"
                )
            else:
                evidence = threshold.source or "—"
            marker = "" if status is threshold.status else " ⚠"
            w(f"| `{threshold.id}` | {threshold.value} {threshold.unit} | "
              f"{threshold.status.value} | **{status.value}**{marker} | "
              + ", ".join(f"`{b}`" for b in backing)
              + f" | {evidence} |")
            for demotion in demotions:
                w(f"| | | | | | ↳ demoted: {demotion} |")
        w("")
        if uncalibrated:
            w(f"{len(uncalibrated)} of {len(self.thresholds)} thresholds are not "
              "calibrated against a golden set.")
            w("")

        w("## 6. Golden sets")
        w("")
        w("| id | version | records | positives | synthetic | PHI | content hash |")
        w("| --- | --- | --- | --- | --- | --- | --- |")
        for golden in self.goldens.values():
            w(f"| `{golden.id}` | {golden.version} | {len(golden.records)} | "
              f"{golden.positives} | {golden.provenance.synthetic} | "
              f"{golden.provenance.contains_phi} | `{golden.content_hash[:19]}…` |")
        w("")

        w("## 7. Verifying this bundle")
        w("")
        w("```")
        w(f"rae verify evidence/{self.run.run_id}")
        w("```")
        w("")
        w("Recomputes every file hash in `MANIFEST.json` and the root hash over "
          "them. A mismatch means the bundle was edited after it was sealed.")
        w("")
        return "\n".join(out)


def verify(directory: Path) -> list[str]:
    """Recompute the bundle's hashes. Returns a list of problems, empty if sound."""
    import json

    manifest_path = directory / MANIFEST
    if not manifest_path.exists():
        return [f"No {MANIFEST} in {directory} — this is not a sealed bundle."]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []

    for name, expected in manifest["files"].items():
        target = directory / name
        if not target.exists():
            problems.append(f"{name}: listed in the manifest but missing")
            continue
        actual = file_hash(target)
        if actual != expected:
            problems.append(f"{name}: content does not match the manifest")

    present = {p.name for p in directory.iterdir() if p.is_file()} - {MANIFEST}
    for extra in sorted(present - manifest["files"].keys()):
        problems.append(f"{extra}: present in the bundle but not in the manifest")

    if content_hash(manifest["files"]) != manifest["root_hash"]:
        problems.append("root hash does not match the file hashes it covers")

    return problems
