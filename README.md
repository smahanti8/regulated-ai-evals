# regulated-ai-evals

![CI](https://github.com/smahanti8/regulated-ai-evals/actions/workflows/ci.yml/badge.svg)

**An evaluation harness for AI systems that have to survive an audit.**

Not a model. Not an application. The scaffolding a regulated AI product needs
so that its claims are backed by evidence produced while the system was being
verified — rather than assembled afterwards from whatever happened to be lying
around.

---

## The argument

Software in medical devices solved this problem decades ago.

IEC 62304 and the design-control regime around it exist because the industry
worked out, expensively, that you cannot inspect safety into software at the
end. So the standard does something that looks bureaucratic and is not: it
requires that the *process* emit the evidence. Every requirement is written
before its test. Every test traces to a requirement. Every deviation is
documented, justified, and signed. When the auditor arrives, nobody assembles
a submission — the submission is the accumulated residue of having built the
thing properly.

Clinical and industrial AI is now rediscovering all of this, badly.

The pattern repeats: a notebook becomes a pipeline, the pipeline acquires a
threshold, the threshold acquires a claim, and the claim goes into a deck. Six
months later somebody asks which dataset supports the number, and the answer
involves archaeology. The evidence is reconstructed. Reconstructed evidence has
a specific failure mode: it is assembled by someone who already knows what
conclusion it needs to support.

The most common instance is a threshold nobody calibrated. Not fraud — a
reasonable first guess that was never revisited, and that by the time the
claim was written had stopped looking like a guess. `0.85`. `90.0`. `5.0`.
Round numbers are a tell.

This repository is the argument that the discipline transfers. Requirements to
tests to results, golden sets under version control, structural coverage of
decision paths, a sealed evidence bundle, and a gate that will not let an
uncalibrated number carry a decision-driving claim without a signed deviation.
The vocabulary is design controls. The subject is AI.

---

## What it does

| | |
|---|---|
| **Requirement-to-test traceability** | Every claim links to the tests that evidence it and their results. Captured *while the tests run*, not inferred afterwards. |
| **Golden-set management** | Datasets identified by content hash, with version, provenance, labeller, and PHI attestation. Edit the data without changing the version and the run fails. |
| **Structural coverage** | Branch coverage scoped to the functions that decide a claim, not the repository. An unexercised branch is reported as a hole in an argument. |
| **Evidence bundle** | One sealed directory, hash-manifested, that opens with what it does *not* support. |
| **Calibration gate** | A claim may not rest on a threshold weaker than its risk class allows. Deviating requires a written, attributed, value-bound acceptance. |

---

## The two systems it is demonstrated against

Both are real repositories by the same author, pinned by identity in
[`sut.lock`](sut.lock) and never read from a working copy. That shared authorship
matters, and it is stated under [what this does not do](#what-this-does-not-do).

**[surgical-fhir-pipeline](https://github.com/smahanti8/surgical-fhir-pipeline)**
@ `e61d181` — maps synthetic robotic-surgery telemetry to FHIR R4B. Scoped here
to the terminology-trust layer.

**[prior-auth-agent](https://github.com/smahanti8/prior-auth-agent)** @ `d883c58`
— a LangGraph agent that drafts prior-authorization determinations (an approval
or an insufficient-evidence result, never a denial) behind a hard citation gate,
with a human review queue and a hash-chained decision log. Scoped here to its
safety properties. Determination accuracy, retrieval quality and the PHI boundary
are declared out of scope rather than left unmentioned. Its source contains this:

```python
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
```

One number decides which cases no human will ever see. It is round, it has an
environment override, and the system's own decision log says of it: "A fixed 0.85
is uncalibrated — plausibly too strict or too lax." That sentence is the reason
the harness has something to say about this system.

---

## What the harness found

Reproduce with `rae fetch && rae run`. Full output:
[`docs/example-bundle/SUMMARY.md`](docs/example-bundle/SUMMARY.md).

### Most claims verify with no threshold at all

Four safety properties of prior-auth-agent verify against 20 tests without a
calibrated number anywhere: a `met` criterion needs both a policy quote and a
chart citation; a citation that does not resolve against the bundle is stripped
and a criterion left with none is downgraded; the drafter cannot emit a denial;
and editing, deleting or reordering a decision-log entry is detected. Their safety
is a refusal, and a refusal needs no calibration.

### The threshold that gates automatic finalization

```
| threshold      | value | declared   | effective  | evidence                                                    |
| THR-CONFIDENCE |  0.85 | calibrated | asserted ⚠ | prior-auth-determinations-v1, recall 1.00 CI [0.21, 1.00], n=1 |
```

Measured against 13 recorded drafts of the system's own golden cases. Five are
approvals and one of those is wrong: `case_008`, an approval at confidence 0.50,
which the gate correctly keeps from automatic finalization. Recall 1.00 from a
single positive gives an interval as wide as the whole range, and no held-out set
exists, so the harness treats the number as `asserted` and reduces `REQ-PA-005` to
what the evidence does support: approvals at or above the threshold go automatic,
everything else goes to a human, and whether 0.85 is the right boundary is not
supported by evidence.

Two more things the bundle records rather than hides. The threshold is read from
the environment, so the evidence describes the default and not necessarily what a
deployment runs. And the labels come from the system's own fixtures, so the set
shows how the gate behaves on those cases, not that they are the right cases.

### The clinical system, which fails differently

Five terminology claims, four verified cleanly with **no thresholds at all**.
Its safety comes from a categorical refusal — `UnmappedConceptError` rather than
an uncoded concept — and a refusal needs no calibration.

The one claim that does need a boundary is the one with no boundary behind it.
The pipeline measures its concept map honestly (11 bindings, 5 verified, 6
provisional — **55% not clinically safe**) and publishes the number. Nothing
consumes it. So "the concept map is fit for clinical exchange" is downgraded
to what is actually supported: *the split is measured and published; whether it
is adequate is not decided anywhere in the system.*

### A coverage hole, found and closed

The first reference run reported `DP-PA-CHAIN-VERIFY` at **8 of 10 branches**
(`verify_chain`, `audit_log.py`). The tests showed that edited, deleted and
reordered entries are detected, but never called it on a missing log or on a log
with blank lines. Two tests closed it, and the bundle here is the run after.
Closing them also made a limit explicit: a log that does not exist verifies as
empty, so deleting the whole file is not detected. That is the same
tamper-evident-not-tamper-proof boundary the system documents, and `REQ-PA-004`
does not claim more.

### Final state

10 in-scope claims, 10 with passing evidence, **2 blocking the run**, 0 accepted
non-conformances, 2 of 2 thresholds not calibrated. `rae run` exits non-zero.

---

## The calibration gate

The rule:

> A claim may not rest on a threshold whose provenance is weaker than its risk
> class requires. `rae run` exits non-zero.

| risk class | what it means | weakest acceptable threshold |
|---|---|---|
| `informational` | a human reads it and decides independently | `asserted` — someone chose it on purpose |
| `supportive` | drives a decision a human confirms | `inherited` — a spec sheet, a standard |
| `decision_driving` | the system acts, or nobody will overrule it | `calibrated` — measured, on this system |

Three further demotions apply to a threshold that claims to be calibrated:

- **In-sample only.** Fitted and measured on the same set → treated as
  `asserted`. That is not a weak measurement of performance; it is a
  measurement of fit.
- **Stale value.** Calibrated at 5.4 while the source says 5.0 → the evidence
  describes a value the system does not run.
- **Wide interval.** A 95% recall interval wider than 0.20 cannot carry a
  numeric performance claim, however good the point estimate looks.

### Deviating

```bash
rae run --accept-risk THR-CONFIDENCE --rationale "<why this deviation is acceptable, and until when>"
```

The acceptance is written to `risk-acceptances.yaml` (created on first use),
attributed to a named person (from `--accepted-by`, else `git config`; it will
refuse rather than sign anonymously), bound to the threshold's current value,
and carried into the bundle as a non-conformance. It stops the run failing. It
does not make the claim conform, and `conforms: false` stays in the record.

Move the threshold and the sign-off does not follow it — the value hash no
longer matches, the acceptance is reported as stale, and the run fails again.

The escape hatch exists because reality requires deviation. It cannot be used
silently, because that is the failure it was built to prevent.

---

## Setting the policy

The three judgement calls above are **regulatory opinions, not mechanisms**, so
they live as constants at the top of
[`src/regulated_ai_evals/claims.py`](src/regulated_ai_evals/claims.py) where a
change to one shows up in a diff:

```python
REQUIRED_STATUS = {...}                        # the risk-class gradient
IN_SAMPLE_DOWNGRADES_TO = ThresholdStatus.ASSERTED
MAX_CI_WIDTH_FOR_PERFORMANCE_CLAIM = 0.20
```

The values shipped here are defensible defaults, not settled law. They were
reviewed against this repository's own example data and kept; D10 in
[`DECISIONS.md`](DECISIONS.md) records the alternatives and what each would
change. The questions worth arguing about before you adopt them:

- Should a published safety limit (`inherited`) ever be enough for a
  decision-driving claim? Refusing is the purist position; it is also how gates
  get switched off.
- Does in-sample calibration drop one step, or all the way to `asserted`?
- Is 0.20 the right interval width, or should it vary by risk class?

---

## Commands

```bash
pip install -e ".[demo]"   # what the pinned prior-auth-agent imports
```

No API key is needed or used: the demonstration suites call pure functions.
(prior-auth-agent constructs an LLM client when it is imported; nothing calls it.)

```bash
rae fetch      # materialise the pinned systems under test into .sut/
rae check      # validate the register and golden sets; run nothing
rae run        # verify, evaluate claims, seal a bundle. exits non-zero on a gap
rae verify docs/example-bundle   # recompute every hash. the auditor's command
```

A system under test that cannot be reached does not abort the run. `rae fetch`
reports it and continues; its claims appear in the bundle with no evidence,
which is the honest outcome and a more useful one than a stack trace.

Of the eleven files in a bundle, seven are a pure function of the inputs and
come out byte-identical on a different machine — `requirements.json`,
`thresholds.json`, `claims.json`, `goldens.json`, `coverage.json`,
`nonconformances.json` and `traceability.csv`. Verified by running the suite
twice and comparing the two bundles file by file.

The other four differ by construction: `run.json` and `MANIFEST.json` carry the
run id and timestamp, `SUMMARY.md` embeds both, and `results.json` records
per-test durations. So a diff between two bundles isolates what actually
changed about the evidence, and the four noisy files are the ones you would
expect to skip.

```bash
rae calibrate THR-CONFIDENCE --golden prior-auth-determinations-v1 \
  --label-field wrong_approve \
  --objective "keep wrong approve drafts out of automatic finalization at recall >= 0.90"
```

Rebuild the golden set (deterministic; derived from the pinned prior-auth-agent,
so run `rae fetch` first):

```bash
python scripts/build_goldens.py
```

---

## Layout

```
requirements/*.yaml          the claims. written before their tests exist
goldens/<id>/                data.csv + manifest.json (hash, provenance, PHI
                             attestation), derived by scripts/build_goldens.py
calibration/*.yaml           operating points, produced by `rae calibrate`
risk-acceptances.yaml        signed deviations, written by `rae run --accept-risk`
sut.lock                     pinned identity of each system under test
docs/example-bundle/         a sealed bundle, committed so the repo reads without running
DECISIONS.md                 the decisions worth arguing about, each with its strongest counter-argument
src/regulated_ai_evals/
  requirements.py            the register
  trace.py, pytest_plugin.py @verifies — traceability captured at execution time
  goldens.py                 content-hash identity, PHI attestation, identifier scan
  structural.py              branch coverage scoped to declared decision paths
  calibration.py             thresholds, operating points, Wilson intervals, acceptances
  claims.py                  the gate. the module the rest of this exists to serve
  bundle.py                  the sealed artefact
  adapters/                  one per system under test
```

Adapters read threshold **values out of the system's source** rather than
restating them. A restated number is a second copy that drifts silently on the
day someone tunes the first.

---

## What this does not do

- **It is not a signing infrastructure.** The manifest detects drift and casual
  editing. It does not resist a determined forger, and says so.
- **It does not make a system safe.** It makes the gap between what a system
  claims and what it has shown legible, and refuses to let the gap close
  quietly.
- **The identifier scan cannot prove the absence of PHI.** It catches the
  realistic failure — a real extract copied into a fixture and relabelled
  synthetic — and nothing stronger.
- **It has no opinion on model quality.** A well-calibrated threshold on a bad
  model passes every gate here.

---

## A note on the harness's own tests

The tests in `tests/framework/` deliberately carry no `@verifies` marker. The
register describes claims about the systems under test; those tests assert that
the harness works, which is a different kind of evidence and does not belong in
the same matrix. `rae run` executes only the demo suites. Run everything with
`pytest -q`.
