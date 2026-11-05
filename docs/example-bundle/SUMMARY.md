# Evidence bundle 316816c79c23

Generated 2026-10-22T02:38:14+00:00 by regulated-ai-evals 0.1.0.

## 1. What this bundle does not support

Read this section first. Everything below it is the supporting detail.

**2 claim(s) reduced to what the evidence supports.**

- `REQ-PA-005` (decision_driving, now *behavioural*)
  - claimed: Only an approval is finalized automatically, and only when its confidence reaches the threshold and no required criterion is insufficient. Every other case goes to a human.
  - supportable: Approvals at or above the configured confidence threshold with no required criterion insufficient are routed to automatic finalization; every other case is routed to review. Whether 0.85 is the right boundary is not supported by evidence about this system.
  - because: THR-CONFIDENCE: fitted and measured on the same golden set (prior-auth-determinations-v1@1.0.0); no held-out confirmation
  - because: THR-CONFIDENCE is asserted; a decision_driving claim requires calibrated
- `REQ-TX-005` (decision_driving, now *behavioural*)
  - claimed: The concept map is fit for clinical exchange.
  - supportable: The verified/provisional split is measured and published. Whether it is adequate is not decided anywhere in the system.
  - because: THR-FHIR-PROVISIONAL-CEILING is uncalibrated; a decision_driving claim requires calibrated

## 2. Declared out of scope for this run

Not gaps. Claims this run did not undertake to verify. The distinction is deliberate: a boundary is a decision, a gap is a defect, and an auditor needs to be told which is which.

- `REQ-PA-010` — The drafted determination agrees with clinical ground truth.
  - Measured in prior-auth-agent's own golden evaluation (its EVALS.md), on recorded model output. It is not asserted or re-measured in this run.
- `REQ-PA-011` — Retrieval surfaces the policy passage that each criterion is drawn from.
  - Requires the vector store and the policy corpus. Retrieval quality is not evaluated at the pinned revision.
- `REQ-PA-012` — Patient data stays inside the deployment's PHI boundary.
  - The repository's Terraform is documentation-grade and has never been applied, so there is no deployment to verify against.
- `REQ-TX-010` — A case with an unmapped procedure code or missing laterality is dropped rather than degraded.
  - Requires mapping.py and the synthetic case generator. This run scopes to the terminology-trust layer.
- `REQ-TX-011` — No raw medical record number reaches FHIR output.
  - Requires mapping.py. Named here because an evidence bundle that silently omits the identifier-boundary claim invites the reader to assume it was covered.
- `REQ-TX-012` — The quality report states the exchangeable fraction and attributes every dropped case to the element that caused the drop.
  - Requires quality.py and mapping.py.

## 3. Systems under test

| system | kind | pinned at |
| --- | --- | --- |
| surgical-fhir-pipeline | git | `e61d181281ffb681545` |
| prior-auth-agent | git | `d883c58647c723aee1a` |

## 4. Claims

| requirement | risk class | scope | evidence | claim supported |
| --- | --- | --- | --- | --- |
| `REQ-PA-001` | decision_driving | in_scope | 4 test(s), all passing | performance |
| `REQ-PA-002` | decision_driving | in_scope | 8 test(s), all passing | performance |
| `REQ-PA-003` | decision_driving | in_scope | 2 test(s), all passing | performance |
| `REQ-PA-004` | supportive | in_scope | 6 test(s), all passing | performance |
| `REQ-PA-005` | decision_driving | in_scope | 5 test(s), all passing | behavioural |
| `REQ-PA-010` | decision_driving | out_of_scope | not undertaken | — |
| `REQ-PA-011` | decision_driving | out_of_scope | not undertaken | — |
| `REQ-PA-012` | decision_driving | out_of_scope | not undertaken | — |
| `REQ-TX-001` | decision_driving | in_scope | 2 test(s), all passing | performance |
| `REQ-TX-002` | decision_driving | in_scope | 4 test(s), all passing | performance |
| `REQ-TX-003` | informational | in_scope | 1 test(s), all passing | performance |
| `REQ-TX-004` | supportive | in_scope | 1 test(s), all passing | performance |
| `REQ-TX-005` | decision_driving | in_scope | 1 test(s), all passing | behavioural |
| `REQ-TX-010` | decision_driving | out_of_scope | not undertaken | — |
| `REQ-TX-011` | decision_driving | out_of_scope | not undertaken | — |
| `REQ-TX-012` | informational | out_of_scope | not undertaken | — |

## 5. Thresholds

Declared status is what the repository asserts. Effective status is what the evidence supports, and it is the one the gate uses.

| threshold | value | declared | effective | backs | evidence |
| --- | --- | --- | --- | --- | --- |
| `THR-CONFIDENCE` | 0.85 confidence (0-1) | calibrated | **asserted** ⚠ | `REQ-PA-005` | prior-auth-determinations-v1@1.0.0, recall 1.00 CI [0.21, 1.00], n=1 |
| | | | | | ↳ demoted: fitted and measured on the same golden set (prior-auth-determinations-v1@1.0.0); no held-out confirmation |
| `THR-FHIR-PROVISIONAL-CEILING` | 0.0 fraction of bindings | uncalibrated | **uncalibrated** | `REQ-TX-005` | — |

2 of 2 thresholds are not calibrated against a golden set.

## 6. Golden sets

| id | version | records | positives | synthetic | PHI | content hash |
| --- | --- | --- | --- | --- | --- | --- |
| `prior-auth-determinations-v1` | 1.0.0 | 13 | 1 | True | False | `sha256:8f0bf8dd79f5…` |

## 7. Verifying this bundle

```
rae verify evidence/316816c79c23
```

Recomputes every file hash in `MANIFEST.json` and the root hash over them. A mismatch means the bundle was edited after it was sealed.
