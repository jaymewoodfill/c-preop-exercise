# HIPAA and Healthcare Privacy Notes

This take-home is not a HIPAA compliance implementation and should not be treated as production-ready healthcare infrastructure. It demonstrates privacy-aware design choices that are relevant to HIPAA-aligned systems processing patient-like data.

## Scope

The project is a local CLI/evaluation harness for one triage function:

- No production users.
- No persistent database.
- No real patient records intended.
- No network service by default.
- No default third-party API disclosure.

Because of that, several HIPAA Security Rule safeguards are documented as production requirements rather than implemented directly.

## PHI/PII in this assignment

The sample submission shape includes patient-like fields that would be sensitive in a real environment:

- patient ID
- MRN
- name
- date of birth
- sex
- clinical documents/free text
- medications/conditions
- labs/vitals
- procedure details

Even when sample data is synthetic, the code treats it as sensitive to avoid building unsafe defaults.

## Minimum Necessary principle

HIPAA's Minimum Necessary concept is a useful design lens: disclose only the information needed for the task.

Implemented privacy-aware choices:

- Triage output focuses on decision, issue category, evidence source, and policy-relevant details.
- Patient name, MRN, DOB, and sex are not copied into normal output because policy rules do not require them.
- Baseline/eval artifacts store submission fingerprints instead of duplicating full submissions.
- Generated reports omit full patient submissions by default.
- Tests assert unrelated patient identifiers are not echoed in output.

Important tradeoff:

- The assignment requires exact evidence values/dates/excerpts for issues.
- In production, evidence display should be restricted to authorized roles and minimized/redacted where possible.

## Access controls

Implemented for demonstration:

- `auth.py` provides an optional service-boundary example.
- Signed bearer token verification.
- Token expiration check.
- Required scope check: `triage:evaluate`.
- Tenant/account match before triage execution.
- Rejection of patient-ID-only cross-tenant access.

Production requirements:

- Use an identity provider rather than the demo HMAC token format.
- Validate JWT/JWKS issuer, audience, signature, expiration, and scopes.
- Enforce tenant/patient/case authorization server-side.
- Never trust client-supplied `patient.id`, `mrn`, or `case_id` as proof of access.
- Use least-privilege roles for viewing clinical evidence.

## Audit controls

Not implemented because this is a local harness with no real users or persistence.

Production systems should audit:

- user identity
- tenant/account
- case/patient accessed
- time of access
- action performed: evaluate, view, export, delete
- authorization failures
- report generation/access

Avoid logging:

- full clinical notes
- MRNs/names/DOBs
- full request/response payloads
- evidence excerpts unless required and access-controlled

## Integrity controls

Implemented or partially implemented:

- Pydantic schema validation.
- Deterministic rule engine.
- Baseline/eval submission fingerprint binding.
- Eval rejects case ID or fingerprint mismatches.
- Tests cover adversarial splicing/mismatch cases.

Production additions:

- Tamper-evident audit logs.
- Signed or versioned policy definitions.
- CI checks for deterministic behavior and security regressions.
- Database integrity constraints around tenant/case ownership.

## Transmission security

Current local workflows do not transmit patient-like data externally by default.

Production requirements:

- TLS for all service communication.
- Encrypted service-to-service channels.
- Secure cookie/session configuration if browser-based.
- No PHI in URLs, query strings, or client-side logs.

## Storage, retention, and disposal

Current safeguards:

- Generated baseline/eval/determinism reports are gitignored.
- Reports omit full submissions by default.

Production requirements:

- Defined retention schedule.
- Secure deletion/disposal process.
- Encrypted storage where PHI is persisted.
- Backups governed by the same retention/access policies.
- Separate demo/eval data from production PHI.

## Business Associate and third-party API considerations

The deterministic implementation avoids default third-party disclosure.

If an LLM or external service is introduced later:

- Treat patient-like prompts/documents as potential PHI.
- Confirm contractual/privacy approval before sending data externally.
- Determine whether a Business Associate Agreement or equivalent is required.
- Minimize prompt content.
- Avoid persistent memory/training on patient data.
- Validate outputs and keep deterministic policy engine as source of truth.

## De-identification and demo data

Recommended practices:

- Use synthetic or de-identified datasets for demos/evals.
- Avoid real MRNs, names, DOBs, addresses, phone numbers, emails, and document excerpts in committed fixtures.
- Prefer stable case IDs and fingerprints for correlation.
- Keep generated reports out of source control.

## Incident response considerations

Production systems should define:

- how suspected PHI exposure is reported
- who investigates
- log/evidence preservation process
- containment steps
- notification decision process
- post-incident remediation tracking

This take-home does not implement an incident response workflow, but generated artifacts and external API usage are minimized by default to reduce exposure risk.

## Summary of implemented privacy-aware controls

| Area | Implemented in take-home |
| --- | --- |
| Minimum Necessary | Avoids copying unrelated patient identifiers into normal output. |
| Access control boundary | Optional `auth.py` wrapper with signed token, scope, and tenant checks. |
| Third-party disclosure | No default LLM/API calls. |
| Artifact minimization | Baseline/eval artifacts omit full submissions. |
| Integrity | Submission fingerprint binding in eval flow. |
| Auditability | Documented production requirements; not implemented locally. |
| Transmission security | Not applicable locally; documented production requirement. |
| Retention/disposal | Generated reports are gitignored; production retention documented. |

The goal is to show healthcare privacy judgment while keeping the assignment focused on the requested triage function.
