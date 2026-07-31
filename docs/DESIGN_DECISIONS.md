# Design Decisions

This document explains the key engineering choices behind the pre-op triage implementation.

## 1. Deterministic rule engine instead of an LLM call

The starter implementation made one LLM call. I replaced it with deterministic policy code because the provided policy is explicit and finite.

Benefits:

- Repeatable outputs for the determinism harness.
- Easier debugging when a case fails scoring.
- No PHI/PII egress to an external model provider.
- No prompt-injection decision path.
- Lower operational cost and latency.
- Clear mapping from assignment policy to code and tests.

This is not an anti-LLM position. It is a fit-for-purpose architecture choice: deterministic source-of-truth logic is better for explicit scheduling criteria.

## 2. Safe LLM extension point, if needed later

If future examples required deeper free-text interpretation, I would add a narrow classifier behind the deterministic engine rather than replacing the engine with an agent.

Candidate classifier task:

```json
{
  "document_type": "H_AND_P | CONSENT | ANTICOAG_PLAN | OTHER",
  "is_signed_consent": true,
  "is_clear_anticoag_plan": false,
  "evidence_excerpt": "..."
}
```

Security controls I would require:

- Treat document text as untrusted data, not instructions.
- Use strict JSON schema validation.
- Use temperature `0` and deterministic post-processing.
- Validate model output against policy expectations.
- Fall back conservatively to `NEEDS_FOLLOW_UP` on malformed/ambiguous output.
- Add red-team fixtures for prompt injection, false consent claims, and negated anticoagulation plans.
- Keep the deterministic rule engine as the final decision-maker.
- Avoid sending patient-like data externally unless product/privacy requirements explicitly allow it.

## 3. No web service or auth layer in this submission

The assignment asks for `triage_submission(...)` and provides a local eval harness. I intentionally did not add a web API, database, auth layer, or tenant model.

Reasoning:

- Those would be important in production, but would add noise to the take-home.
- Access control cannot be correctly implemented without a trusted identity/session boundary.
- A fake auth layer would create complexity without improving the assignment output.

Instead, `SECURITY.md` and `docs/POLICY_COVERAGE.md` document where authN/authZ and tenant isolation belong if this engine is deployed behind an API.

## 4. Evidence excerpts are included only where required

The prompt requires every issue to cite exact field values, dates, or document excerpts used. The implementation keeps evidence focused on policy-relevant fields and avoids copying unrelated patient identifiers such as MRN/name into normal outputs.

Production tradeoff:

- Evidence is useful for clinical operations review.
- Evidence may contain PHI/PII.
- A production system should role-gate evidence display and avoid logging full excerpts unless explicitly required.

## 5. Fail-closed behavior

Missing or unknown policy-critical data produces `NEEDS_FOLLOW_UP` rather than trying to infer readiness.

Examples:

- Missing procedure date.
- Missing procedure risk.
- Unknown anticoagulant active status.
- Missing latest blood pressure or temperature.
- Missing required documents or labs.

This matches the assignment policy and avoids unsafe optimistic scheduling decisions.

## 6. Decision precedence

The final decision follows a simple precedence rule:

1. Any acute safety exclusion → `NOT_CLEARED`.
2. Else any issue → `NEEDS_FOLLOW_UP`.
3. Else → `READY`.

The engine still returns follow-up issues when `NOT_CLEARED` is present, because those items may remain useful for operational follow-up.

## 7. Dependency minimization

No new runtime dependency was added beyond the starter stack. This reduces supply-chain surface and keeps reviewer setup simple.

## 8. Testing strategy

The tests are split by intent:

- `tests/test_triage_submission.py` covers core policy behavior.
- `tests/test_security_regression.py` covers adversarial/security/privacy behavior.
- `tests/test_policy_boundaries.py` covers date and threshold boundaries.

This separation makes it easier to understand whether a failure is policy logic, boundary math, or security regression.
