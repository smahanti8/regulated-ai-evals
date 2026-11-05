# Decision log

The decisions in this harness worth arguing about, one entry each: the context
that forced a choice, the choice, why, and the strongest argument against it. If
a counter-argument ever wins, the entry gets superseded here, not silently
rewritten.

---

## D1. Verification evidence is captured while the tests run

**Context.** A traceability matrix can be produced two ways: by a tool that walks
the source afterwards and infers which tests cover which requirement, or by
having the run itself record the link. The first is easy to generate and easy to
fake.

**Decision.** A test declares the requirements it evidences with
`@verifies("REQ-...")`, and a pytest plugin records the link, with the outcome,
when the test runs. `rae run` reads that ledger back.

**Rationale.** The requirement id has to be present in the source at the moment
the assertion runs, so the matrix cannot claim coverage that did not execute.
An id that is not in the register is not rejected at import time; it is reported
as a finding, because failing at collection would let one typo stop the suite
from running and destroy the evidence being gathered.

**Counter-argument.** It ties the harness to pytest, and a decorator proves only
that a test claims a requirement, not that its assertions are relevant to it.
Relevance is still a human review.

---

## D2. Claims outside a run's scope are declared, not omitted

**Context.** A matrix that lists only the claims that were verified cannot tell a
reader whether the others were deliberately excluded or overlooked.

**Decision.** The register carries out-of-scope claims with a stated reason, and
every bundle prints them in their own section, "Declared out of scope", after the
claims the evidence does not support.

**Rationale.** A boundary is a decision and a gap is a defect; a reader needs to
be told which is which. It also stops a bundle that says nothing about, for
example, determination accuracy from being read as having covered it.

**Counter-argument.** Declaring a claim out of scope costs nothing, so the list
can flatter: it can make a narrow run look thorough. The reasons have to be
specific and checkable, and nothing here enforces that.

---

## D3. Coverage is measured against declared decision paths, not the repository

**Context.** Repository-wide coverage says how much code the suite touched. It
does not say whether the code that decides a particular claim was exercised.

**Decision.** Each claim's code is declared as a decision path (a function), and
structural coverage is reported per path, with branch denominators counted from
the AST of that function's span instead of taken from coverage.py's file totals.
An unexercised branch inside a claim-bearing function is described as a hole in
the argument for that claim.

**Rationale.** It asks the question a safety standard actually asks: has every
path through the code that decides this claim been exercised. A well-tested
helper cannot mask an untested decision.

**Counter-argument.** The paths are declared by the author, so an undeclared path
is invisible. And branch coverage cannot see inside a compound condition: in the
reference bundle the auto-finalization gate reports 0 of 0 branches and
"complete", although its decision has three independent conditions. Only tests
of each condition show they were exercised independently, which is what
condition-level coverage would measure.

---

## D4. A claim may not rest on a threshold weaker than its risk class allows

**Context.** The most common evidence failure is a threshold nobody calibrated: a
reasonable first guess that was never revisited and, by the time the claim was
written, had stopped looking like a guess.

**Decision.** Thresholds carry a provenance status (asserted, inherited,
calibrated, uncalibrated). Each risk class has a weakest acceptable status:
informational needs asserted, supportive needs inherited, decision-driving needs
calibrated. A claim resting on a weaker threshold is reduced to what the evidence
supports, and a decision-driving claim in that position makes `rae run` exit
non-zero. Three further demotions apply to a threshold that says it is
calibrated: it was fitted and measured on the same set, the evidence describes a
stale value, or the recall interval is wider than 0.20.

**Rationale.** If the system acts, or no one will realistically overrule it, the
boundary has to have been measured on data from that system. A published limit
is not a claim about your detector, and an in-sample operating point measures
fit, not performance.

**Counter-argument.** The gradient, the in-sample rule and the 0.20 width are
regulatory opinions, kept as constants at the top of `claims.py` so a change
shows in a diff. The values were reviewed and kept before publication (D10).
Whether an inherited limit should ever suffice for
a decision-driving claim is contested: refusing is the purist position, and it is
also how gates get switched off.

---

## D5. A deviation is signed, dated and bound to the value it was granted for

**Context.** A gate that cannot be passed gets removed. A gate that can be passed
silently is no gate.

**Decision.** `rae run --accept-risk THR-ID --rationale "..."` records a
non-conformance in the repository and in the bundle, attributed to a named
person, dated, and bound to the hash of the threshold's current value. It
refuses to sign anonymously. Moving the threshold invalidates the acceptance and
the run fails again.

**Rationale.** A sign-off is granted for a number, not for a name. Binding it to
the value's hash means changing the constant reopens the question.

**Counter-argument.** The named person comes from `--accepted-by` or from git
config, which anyone can set. This is a record, not signing infrastructure: the
manifest detects casual edits and does not resist a determined forger.

---

## D6. Systems under test are pinned by identity and fetched, never read from a working copy

**Context.** A bundle that cannot name the exact code it tested is not evidence,
and "whatever is checked out on this machine" is not a name.

**Decision.** `sut.lock` pins each system by commit SHA (or, for code outside
version control, by content hash). `rae fetch` materialises it into a gitignored
`.sut/` and refuses if what it gets does not match the pin. The identity goes in
the bundle.

**Rationale.** Two alternatives were rejected. Submodules bind the pin to this
repository's git state rather than to the run, and sibling clones test whatever
happens to be checked out, so a run cannot be reproduced on another machine.

**Counter-argument.** Fetching needs network access, and a content-hash pin is
weaker provenance than a SHA: it shows the code has not changed, not who wrote it
or when.

---

## D7. Thresholds are read out of the system's source, not restated

**Context.** A threshold declared twice, once in the system and once in the
register, drifts silently the day someone tunes the first.

**Decision.** Adapters read a threshold's value out of the system's source by AST.
For a value written as `float(os.getenv(VAR, "<literal>"))` the adapter reads the
default and records the name of the variable, because the source pins only the
default.

**Rationale.** Reading from source gives the value-binding on deviations its
teeth: change the constant and the hash moves. Parsing instead of importing means
the harness does not execute the system to read a number.

**Counter-argument.** Only literals and the environment-default pattern are
readable; anything computed is refused. And for an environment-defaulted
threshold the evidence describes the default, not necessarily what a deployment
runs.

---

## D8. The demonstration systems have known provenance, and their labels are not independent

**Context.** The harness needs real systems to bind against. An earlier
candidate, a loose script with no recorded author or terms, was replaced: a
repository about provenance cannot ship evidence about code whose provenance it
cannot state.

**Decision.** The two systems are surgical-fhir-pipeline and prior-auth-agent,
by the same author as this harness, pinned by SHA. The golden set for the
confidence threshold is derived from prior-auth-agent's own recordings and
fixtures by a script that refuses to run against any other revision.

**Rationale.** Known authorship, public terms, and a build script anyone can
re-run.

**Counter-argument.** The labels come from the system's own fixtures, written by
the same author, so they show how the system behaves on its own cases, not that
those cases are right. The harness demonstrates a method; it is not an
independent audit of either system.

---

## D9. The reference bundle is committed, though it is generated output

**Context.** The usual rule is never to commit build output.

**Decision.** One sealed bundle from a real run is committed under
`docs/example-bundle/`, so the repository can be read without running it.

**Rationale.** The bundle is the deliverable, and a reader should not have to
fetch two repositories and run a suite to see what one looks like. Seven of its
eleven files are a pure function of the inputs and reproduce byte-for-byte on
another run; the other four carry run ids, timestamps and durations.

**Counter-argument.** Committed generated files drift. Change the claims policy
or the register and the bundle describes the old policy until someone re-runs and
re-copies it. `rae verify` checks that a bundle is intact, not that it is current.

---

## D10. The claims policy was reviewed against the example data and kept as shipped

**Context.** Three constants in `claims.py` are regulatory opinions rather than
mechanisms (D4): the risk-class gradient, where an in-sample calibration lands,
and the widest recall interval that may carry a performance claim. They shipped
as defaults. Before publication each was reviewed by running the claims gate
under the alternatives against this repository's own example data.

**Decision.** Kept as shipped. Informational needs `asserted`, supportive needs
`inherited`, decision-driving needs `calibrated`; an in-sample calibration falls
to `asserted`; the widest interval that may carry a performance claim is 0.20.

**Rationale.** A published limit says nothing about the system under test, an
in-sample number measures fit rather than performance, and 0.20 needs roughly 70
positives, which is what stops three-for-three on a ten-row file from becoming a
claim. Measured on the example: under every single change tried, both blocked
claims stayed blocked. REQ-PA-005 unblocks only if the policy is weakened
(decision-driving accepting `asserted`, or accepting `inherited` together with a
one-step in-sample downgrade), which would remove the finding the example exists
to show. REQ-TX-005 stays blocked under every setting because its threshold is
declared uncalibrated. The interval gate applies only to decision-driving claims,
and the example's interval is 0.79 wide (one positive), so it fails at every
width up to 0.80.

**Counter-argument.** One example's insensitivity says little about an adopter.
A team holding a published safety limit and no calibration data may find
"calibrated or blocked" too strict and switch the gate off, which is the failure
the README names. 0.20 is out of reach for many real golden sets, and dropping an
in-sample result one step rather than two is defensible. A different set of
claims could be sensitive where this one is not. That is why the constants stay
visible in a diff and not behind configuration.
