# Production Hardening Notes

This take-home implementation is a local deterministic rule engine. If it were deployed as part of a production clinical operations system, I would add the following controls around it.

## API and access control boundary

`auth.py` includes a dependency-free HMAC bearer-token example to make this boundary concrete for the take-home. In production, replace it with an identity provider and JWT/JWKS validation.

- Authenticate every caller.
- Verify token signature, issuer/audience, expiry, and required scopes.
- Derive tenant/account scope from trusted auth context, not request JSON.
- Authorize access to each patient/case before invoking `triage_submission(...)`.
- Fetch submissions using tenant-scoped keys, e.g. `(tenant_id, case_id)`.
- Prevent IDOR/BOLA by denying direct cross-tenant access to patient IDs, MRNs, case IDs, document IDs, and generated reports.
- Apply least-privilege roles for viewing evidence excerpts.

## PII/PHI minimization

- Avoid logging full submissions.
- Avoid logging MRNs, names, DOBs, and full document text.
- Redact or tokenize identifiers where logs need correlation IDs.
- Role-gate evidence display because evidence may contain clinical excerpts.
- Set retention windows for generated reports and triage outputs.
- Encrypt persisted submissions/reports where product requirements require storage.

## Auditability

Log security-relevant events without excessive PHI:

- Who accessed a case.
- Which tenant/account was used.
- Which case ID was evaluated.
- Whether output was generated, viewed, exported, or deleted.
- Decision category counts, not full clinical text, for operational metrics.

## Input and runtime safeguards

- Enforce request size limits.
- Set timeouts at API gateway/server layer.
- Validate JSON content type and schema before processing.
- Reject unexpected file uploads unless explicitly supported.
- Use rate limits to protect batch/eval endpoints.
- Keep `triage_submission(...)` side-effect-free.

## Dependency and CI hygiene

Recommended checks:

- Unit tests.
- Security regression tests.
- Determinism check.
- Dependency vulnerability scan.
- Static analysis / linting.
- Secret scanning.
- Generated report files excluded from commits.

## If an LLM is introduced later

Use an LLM only for narrow extraction/classification tasks, not as the final policy decision-maker.

Required controls:

- Explicit prompt-injection isolation: document text is data, not instructions.
- Strict JSON schema output.
- Temperature `0`.
- Output validation and conservative fallback.
- No tool-calling or external browsing from document text.
- No persistent memory over patient records.
- Adversarial fixtures in CI.
- Privacy review before sending patient-like data to any third party.

## Deployment misconfiguration risks

Avoid:

- Debug logs containing submissions or evidence excerpts.
- Public buckets/shared drives for reports.
- Broad database roles that bypass tenant filters.
- Client-side-only authorization checks.
- Trusting `patient.id`, `mrn`, or `case_id` from request JSON for access control.
- Using the demo HMAC token format from `auth.py` as-is for production identity.
- Storing API keys in repo or generated reports.

## Operational monitoring

Track aggregate, non-PHI metrics:

- Output decision distribution.
- Issue category distribution.
- Validation failure count.
- Determinism check failures.
- Latency and error rate.
- Access denied events.

These metrics help detect regressions without exposing patient details.
