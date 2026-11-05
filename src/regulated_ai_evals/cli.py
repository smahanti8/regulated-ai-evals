"""`rae` — the harness command line.

    rae fetch       materialise the pinned systems under test into .sut/
    rae check       validate the register and the golden sets; run nothing
    rae calibrate   measure a threshold's operating point and record it
    rae run         execute the verification suite and seal an evidence bundle
    rae verify      recompute a bundle's hashes

`run` is the one with an opinion. It exits non-zero when a claim rests on a
threshold that has not been calibrated to the standard its risk class demands.
`--accept-risk` is the way past, and it writes a signed, dated, value-bound
non-conformance into the repository and into the bundle. The escape hatch
exists because reality requires deviation. It cannot be used silently because
that is the failure it was built to prevent.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

from .adapters import build_all
from .adapters.base import SourceConstantError
from .bundle import Bundle, verify as verify_bundle
from .calibration import (
    CalibrationEvidence,
    RiskAcceptanceLedger,
    Threshold,
    ThresholdStatus,
    save_evidence,
)
from .claims import effective_status, evaluate as evaluate_claims
from .goldens import GoldenSetError, load_all
from .identity import RunRecord, accepting_party
from .requirements import RegisterError, RequirementRegister
from .structural import CoverageUnavailable, measure as measure_coverage
from .sut import FetchError, fetch, load_lock
from .trace import TraceLedger

ROOT = Path.cwd()
LOCK = ROOT / "sut.lock"
SUT_DIR = ROOT / ".sut"
REQUIREMENTS_DIR = ROOT / "requirements"
GOLDENS_DIR = ROOT / "goldens"
CALIBRATION_DIR = ROOT / "calibration"
EVIDENCE_DIR = ROOT / "evidence"
ACCEPTANCES = ROOT / "risk-acceptances.yaml"
TRACE_FILE = ROOT / ".rae-trace.json"
COVERAGE_JSON = ROOT / ".rae-coverage.json"

OK, PROBLEM = 0, 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rae", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fetch", help="materialise the pinned systems under test")
    sub.add_parser("check", help="validate the register and golden sets")

    calibrate = sub.add_parser("calibrate", help="measure and record an operating point")
    calibrate.add_argument("threshold_id")
    calibrate.add_argument("--golden", required=True)
    calibrate.add_argument("--holdout")
    calibrate.add_argument("--label-field", required=True)
    calibrate.add_argument("--objective", required=True)

    run = sub.add_parser("run", help="verify, evaluate claims, seal a bundle")
    run.add_argument("--no-bundle", action="store_true")
    run.add_argument(
        "--accept-risk",
        metavar="THR-ID",
        action="append",
        default=[],
        help="accept the calibration gap on this threshold (repeatable)",
    )
    run.add_argument("--rationale", action="append", default=[])
    run.add_argument("--accepted-by")

    verify = sub.add_parser("verify", help="recompute a bundle's hashes")
    verify.add_argument("bundle")

    args = parser.parse_args(argv)
    return {
        "fetch": cmd_fetch,
        "check": cmd_check,
        "calibrate": cmd_calibrate,
        "run": cmd_run,
        "verify": cmd_verify,
    }[args.command](args)


# -- commands --------------------------------------------------------------


def cmd_fetch(_: argparse.Namespace) -> int:
    """Materialise every pinned source, reporting failures per system.

    One unavailable system does not abort the others. A machine that can reach
    GitHub but not some internal mirror should still be able to run the half of
    the suite it can, and be told plainly which half it is missing.
    """
    SUT_DIR.mkdir(exist_ok=True)
    failed: list[str] = []
    for source in load_lock(LOCK):
        try:
            fetch(source, SUT_DIR)
        except FetchError as error:
            failed.append(source.name)
            print(f"  {source.name:<26} UNAVAILABLE: {error}")
            continue
        print(f"  {source.name:<26} {source.kind:<5} {source.pin[:19]}")

    if failed:
        print(f"\n  {len(failed)} system(s) unavailable: {', '.join(failed)}")
        print("  Their tests will be skipped and their claims will appear in the "
              "bundle with no evidence.")
    return PROBLEM if failed else OK


def cmd_check(_: argparse.Namespace) -> int:
    problems: list[str] = []

    try:
        register = RequirementRegister.load(REQUIREMENTS_DIR)
        print(f"  register       {len(register)} requirements, "
              f"{len(register.in_scope())} in scope")
    except RegisterError as error:
        print(f"  register       FAILED: {error}")
        return PROBLEM

    goldens = load_all(GOLDENS_DIR)
    for golden in goldens.values():
        try:
            golden.verify()
            print(f"  {golden.id:<22} {len(golden.records):>5} rows, "
                  f"{golden.positives:>4} positives, hash ok")
        except GoldenSetError as error:
            problems.append(str(error))
            print(f"  {golden.id:<22} FAILED")

    thresholds, _, _, unavailable = _adapter_state()
    for note in unavailable:
        print(f"  unavailable    {note}")
        print("                 run `rae fetch` first")
    declared = register.threshold_ids()
    if unavailable:
        # Every threshold owned by an absent system looks undeclared. Reporting
        # those as register defects would bury the one problem that is real:
        # the system is missing.
        print(f"  thresholds     not checked; {len(unavailable)} system(s) absent")
    else:
        for missing in sorted(declared - thresholds.keys()):
            problems.append(f"requirement cites unknown threshold {missing!r}")
        for orphan in sorted(thresholds.keys() - declared):
            print(f"  note           threshold {orphan} backs no stated claim")

    for problem in problems:
        print(f"  PROBLEM: {problem}")
    return PROBLEM if problems else OK


def cmd_calibrate(args: argparse.Namespace) -> int:
    goldens = load_all(GOLDENS_DIR)
    fit = goldens[args.golden]
    fit.verify()
    holdout = goldens[args.holdout] if args.holdout else None
    if holdout:
        holdout.verify()

    adapter, threshold = _find_measurable(args.threshold_id)
    point = adapter.measure(threshold.id, fit.records, args.label_field)

    if holdout is not None:
        confirm = adapter.measure(threshold.id, holdout.records, args.label_field)
        low, high = confirm.recall_ci
        print(f"  holdout        recall {confirm.recall:.3f} "
              f"CI [{low:.3f}, {high:.3f}] n={confirm.positives}")
        point = confirm

    low, high = point.recall_ci
    print(f"  {threshold.id:<24} at {threshold.value} {threshold.unit}")
    print(f"  recall         {point.recall:.3f}  CI [{low:.3f}, {high:.3f}]  "
          f"width {point.recall_ci_width:.3f}")
    print(f"  precision      {point.precision:.3f}")
    print(f"  counts         tp={point.true_positives} fp={point.false_positives} "
          f"fn={point.false_negatives} tn={point.true_negatives}")

    evidence = CalibrationEvidence(
        fitted_on=fit.ref,
        confirmed_on=holdout.ref if holdout else None,
        fitted_value=threshold.value,
        objective=args.objective,
        fitted_date=date.today(),
        operating_point=point,
    )
    path = save_evidence(CALIBRATION_DIR, threshold.id, evidence)
    print(f"  recorded       {path.relative_to(ROOT)}")
    if evidence.in_sample_only:
        print("  WARNING        no holdout given; this is an in-sample measurement "
              "and the gate will treat it as asserted")
    return OK


def cmd_run(args: argparse.Namespace) -> int:
    register = RequirementRegister.load(REQUIREMENTS_DIR)
    goldens = load_all(GOLDENS_DIR)
    for golden in goldens.values():
        golden.verify()

    thresholds, paths, identities, unavailable = _adapter_state()
    for note in unavailable:
        print(f"  unavailable    {note}")
    if unavailable:
        print("                 run `rae fetch`; claims for these systems will "
              "appear with no evidence")

    run = RunRecord.start(invocation=" ".join(["rae"] + (sys.argv[1:] or ["run"])))
    run.suts = identities

    ledger = RiskAcceptanceLedger.load(ACCEPTANCES)
    _apply_acceptances(args, thresholds, ledger)

    exit_code = _pytest(paths)
    trace = TraceLedger.read(TRACE_FILE) if TRACE_FILE.exists() else TraceLedger()

    in_scope = [r.id for r in register.in_scope()]
    verdicts = evaluate_claims(
        register, thresholds, ledger, verified=trace.verification_map(in_scope)
    )

    try:
        coverage = measure_coverage(COVERAGE_JSON, paths)
    except CoverageUnavailable as error:
        print(f"  coverage       unavailable: {error}")
        coverage = []

    _report(register, trace, verdicts, thresholds)

    blocked = [v for v in verdicts if v.blocks_run]
    if not args.no_bundle:
        directory = Bundle(
            run=run,
            register=register,
            ledger=trace,
            thresholds=thresholds,
            verdicts=verdicts,
            goldens=goldens,
            coverage=coverage,
            sources=[s.to_dict() for s in load_lock(LOCK)],
        ).write(EVIDENCE_DIR)
        print(f"\n  bundle         {directory.relative_to(ROOT)}")

    if blocked:
        print(f"\n  BLOCKED: {len(blocked)} claim(s) rest on thresholds that are not "
              "calibrated to the standard their risk class requires.")
        for verdict in blocked:
            print(f"    {verdict.requirement_id}: "
                  + "; ".join(verdict.blocking_thresholds))
        print("  Calibrate them, or accept the risk in writing:")
        print("    rae run --accept-risk THR-ID --rationale \"...\"")
        return PROBLEM

    return PROBLEM if exit_code != 0 else OK


def cmd_verify(args: argparse.Namespace) -> int:
    problems = verify_bundle(Path(args.bundle))
    if not problems:
        print(f"  {args.bundle}: intact - every file matches the manifest.")
        return OK
    for problem in problems:
        print(f"  {problem}")
    return PROBLEM


# -- helpers ---------------------------------------------------------------


def _adapter_state() -> tuple[dict[str, Threshold], list, list, list[str]]:
    """Interrogate every adapter, tolerating systems that are not present.

    An absent system under test is an ordinary condition — a fresh clone before
    `rae fetch`, or a source this machine cannot reach. It should produce a
    bundle that says so, not a traceback.
    """
    thresholds: dict[str, Threshold] = {}
    paths: list = []
    identities: list = []
    unavailable: list[str] = []

    for adapter in build_all(SUT_DIR, CALIBRATION_DIR):
        try:
            declared = list(adapter.thresholds())
            found = list(adapter.decision_paths())
            identity = adapter.identity()
        except (OSError, SourceConstantError) as error:
            unavailable.append(f"{adapter.name}: {error}")
            continue
        thresholds.update({t.id: t for t in declared})
        paths.extend(found)
        identities.append(identity)

    return thresholds, paths, identities, unavailable


def _find_measurable(threshold_id: str):
    for adapter in build_all(SUT_DIR, CALIBRATION_DIR):
        if not hasattr(adapter, "measure"):
            continue
        try:
            declared = list(adapter.thresholds())
        except (OSError, SourceConstantError) as error:
            raise SystemExit(f"{adapter.name} is not available: {error}") from None
        for threshold in declared:
            if threshold.id == threshold_id:
                return adapter, threshold
    raise SystemExit(
        f"No adapter can measure {threshold_id}. Calibration needs an adapter that "
        "can replay the system under test against a golden set."
    )


def _apply_acceptances(
    args: argparse.Namespace,
    thresholds: dict[str, Threshold],
    ledger: RiskAcceptanceLedger,
) -> None:
    if not args.accept_risk:
        return
    if len(args.rationale) != len(args.accept_risk):
        raise SystemExit(
            "Each --accept-risk needs its own --rationale. An acceptance without a "
            "reason is not an acceptance."
        )
    who = args.accepted_by or accepting_party()
    for threshold_id, rationale in zip(args.accept_risk, args.rationale):
        if threshold_id not in thresholds:
            raise SystemExit(f"Unknown threshold {threshold_id!r}")
        acceptance = ledger.accept(thresholds[threshold_id], rationale, who)
        print(f"  accepted       {threshold_id} by {acceptance.accepted_by}")
    ledger.save()


def _pytest(paths) -> int:
    sources = sorted({str(p.file.parent) for p in paths})
    demos = sorted(
        str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("demo_*") if p.is_dir()
    )
    command = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        f"--source={','.join(sources)}",
        "-m",
        "pytest",
        "-q",
        f"--rae-trace={TRACE_FILE}",
        # Only the verification suites. The harness's own unit tests assert that
        # the harness works, which is not evidence about a system under test and
        # does not belong in the same matrix.
        *demos,
    ]
    result = subprocess.run(command, cwd=ROOT)
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-q", "-o", str(COVERAGE_JSON)],
        cwd=ROOT,
    )
    return result.returncode


def _report(register, trace, verdicts, thresholds) -> None:
    in_scope = register.in_scope()
    unverified = trace.unverified([r.id for r in in_scope])
    unknown = trace.unknown_requirements(set(register.requirements))
    orphans = trace.orphan_tests()
    uncalibrated = [
        t
        for t in thresholds.values()
        if effective_status(t)[0] is not ThresholdStatus.CALIBRATED
    ]

    print()
    print(f"  claims         {len(in_scope)} in scope, "
          f"{len(in_scope) - len(unverified)} with passing evidence")
    print(f"  thresholds     {len(thresholds)} total, {len(uncalibrated)} not calibrated")
    if unverified:
        print(f"  unverified     {', '.join(unverified)}")
    if unknown:
        print(f"  unknown ids    {', '.join(unknown)} (cited by a test, not in the "
              "register)")
    if orphans:
        print(f"  orphan tests   {len(orphans)} test(s) declare no requirement")


if __name__ == "__main__":
    raise SystemExit(main())
