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

## 3. Optional auth boundary, no web service

The assignment asks for `triage_submission(...)` and provides a local eval harness. I did not add a web API, database, persistent users, or production identity layer.

`auth.py` provides a small optional boundary demonstration for service deployments:

- verifies signed bearer tokens,
- checks expiration,
- enforces `triage:evaluate` scope,
- enforces tenant/account match before calling the triage engine.

Reasoning:

- Real access control requires a trusted identity/session boundary and server-side object lookup.
- A full API/auth service would add noise to the take-home.
- A lightweight boundary demonstrates placement and failure modes without making production-readiness claims.

`SECURITY.md`, `docs/PRODUCTION_HARDENING.md`, and `docs/HIPAA_PRIVACY_NOTES.md` document what a production authN/authZ layer would still require.

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

No new core runtime dependency was added beyond Pydantic. Dependency versions are pinned in `pyproject.toml` and locked in `uv.lock` to make CI/reviewer runs reproducible.

## 8. Module layout

The starter expected `core.py`, so `core.py` remains as a compatibility module that re-exports the public API. Implementation details are split by responsibility:

- `models.py` — Pydantic schemas and type aliases.
- `rules.py` — deterministic policy engine and rule-specific helpers.
- `evidence.py` — issue/evidence/explanation builders.
- `parsing.py` — date, number, text normalization, and excerpt helpers.
- `llm_prompt.py` — legacy prompt helpers isolated from the default deterministic path.
- `auth.py` — optional service-boundary authentication/authorization wrapper.

This keeps the take-home compatible with the harness while avoiding an ever-growing `core.py`.

## 9. Testing strategy

The tests are split by intent:

- `tests/test_triage_submission.py` covers core policy behavior.
- `tests/test_security_regression.py` covers adversarial/security/privacy behavior.
- `tests/test_policy_boundaries.py` covers date and threshold boundaries.
- `tests/test_pentest_regression.py` covers pentest-derived regressions.
- `tests/test_auth.py` covers the optional auth boundary.

This separation makes it easier to understand whether a failure is policy logic, boundary math, or security regression.
