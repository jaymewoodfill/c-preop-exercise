# Security Considerations

This project processes patient-like JSON and free-text clinical documents. The implementation is a local deterministic rule engine, not an autonomous LLM agent, so many LLM and web-app risks are intentionally reduced by design. This document captures the relevant threat model, controls, and test coverage.

## Security posture summary

- No runtime LLM/API calls.
- No secrets required for baseline/eval/determinism workflows.
- No network calls from `triage_submission(...)`.
- No dynamic code execution from patient input.
- Patient submission text is treated as untrusted data and used only as evidence.
- Invalid, future-dated, or non-finite vitals do not suppress older valid acute exclusions.
- Bare keywords in arbitrary notes do not satisfy H&P or consent requirements.
- Fake/cancelled lab codes such as `NOT-CBC` do not satisfy CBC/CMP gates.
- Invalid or missing rule-critical data fails closed to `NEEDS_FOLLOW_UP`.
- Acute safety exclusions take precedence and return `NOT_CLEARED`.
- Baseline/eval artifacts omit full submissions by default.

## Threat model

### Assets

- Patient-like submission JSON.
- Triage decision and issues.
- Evidence fields that may contain clinical note excerpts.
- Patient identifiers and demographics such as patient ID, MRN, name, date of birth, and sex.
- Evaluation outputs under `data/`.

### Trust boundaries

- Input JSON is untrusted.
- Free-text `documents[].text` is untrusted.
- Local evaluation harness is trusted developer tooling.
- No account, tenant, database, browser, or web server boundary is in scope for current implementation.
- No external model or API receives patient-like data during default `make baseline`, `make evals`, or `make determinism` workflows.

### Primary security goals

1. Do not let free text instruct or override policy logic.
2. Do not expose patient-like data to third-party services by default.
3. Do not execute or deserialize input unsafely.
4. Produce schema-valid deterministic output.
5. Make missing/unknown clinical policy data explicit and conservative.
6. Minimize patient identifiers in outputs unless required as evidence.
7. Prevent cross-account or cross-patient data exposure if this rule engine is later wrapped by an API.

## OWASP Top 10 for LLM Applications mapping

This solution avoids an LLM decision path, but the OWASP LLM risks are still useful as a design checklist.

| OWASP LLM risk | Applicability | Control in this repo |
| --- | --- | --- |
| Prompt Injection | Relevant because clinical notes may contain instruction-like text | No LLM consumes note text; tests verify prompt-injection-style notes cannot mark a case `READY` or forge consent. |
| Sensitive Information Disclosure | Relevant because inputs resemble PHI/PII | No runtime API calls by default; generated reports omit full submissions; generated files are ignored; README says no API key required; outputs avoid copying unrelated patient identifiers. |
| Supply Chain | Relevant to all software | Minimal dependencies inherited from starter; no added runtime dependencies; use lockfile/`uv` in reviewer environment if available. |
| Data and Model Poisoning | Low current applicability | No training, fine-tuning, RAG, embeddings, or persistent model memory. |
| Improper Output Handling | Relevant because output may feed downstream scheduling workflows | Output is Pydantic-validated `TriageOutput`; evidence paths/details are deterministic strings. |
| Excessive Agency | Not applicable in current architecture | Engine cannot call tools, mutate records, schedule surgeries, send messages, or access network. |
| System Prompt Leakage | Not applicable in current architecture | No hidden prompt or model system instructions are used for decisions. |
| Vector and Embedding Weaknesses | Not applicable | No vector store, retrieval, or embeddings. |
| Misinformation / Overreliance | Relevant to clinical-adjacent decision support | Policy-only deterministic rules; README documents assumptions; missing data fails closed. |
| Unbounded Consumption | Low current applicability | Local linear scan over one submission; JSONL input size and determinism `--runs` are bounded; no model token costs or recursive tool use by default. |

## OWASP Web/Application Top 10 mapping

This is a local CLI/library implementation, not a web service. Items below focus on what is relevant if the engine is later wrapped in an API.

| OWASP AppSec risk | Applicability | Current/future control |
| --- | --- | --- |
| Broken Access Control | Not applicable inside the local pure function, but critical if exposed as API | Enforce authentication, tenant scoping, patient-level authorization, and server-side object lookup outside `triage_submission`; never trust client-supplied account/patient identifiers alone. |
| Cryptographic Failures | Low locally | Do not commit real patient data or secrets; if deployed, use TLS and encrypted storage/log sinks. |
| Injection | Relevant for untrusted JSON/text | No SQL, shell, template execution, or `eval`; document text is parsed with deterministic string/date checks only; TUI report strings are Rich-markup escaped. |
| Insecure Design | Relevant | Conservative state machine: missing/unknown data → `NEEDS_FOLLOW_UP`; acute exclusions → `NOT_CLEARED`. |
| Security Misconfiguration | Low locally | `.gitignore` excludes generated reports and local env files; eval is local-only by default; OpenAI Eval is explicit opt-in. If deployed, disable debug logs containing PHI. |
| Vulnerable and Outdated Components | Relevant | No added runtime dependencies; keep starter dependencies current via `uv`/dependency updates. |
| Identification and Authentication Failures | Not applicable locally | Required only if converted into network service. |
| Software and Data Integrity Failures | Relevant to evaluation/release | Keep deterministic tests/evals in CI; avoid loading untrusted plugins or code. |
| Security Logging and Monitoring Failures | Low locally | If deployed, log decisions/issue categories without unnecessary document excerpts, MRNs, names, or other PHI/PII. |
| SSRF | Not applicable | No outbound URL fetching. If future document ingestion fetches URLs, enforce allowlists and timeouts. |

## PII/PHI and cross-account access considerations

Current implementation is a local function with no account/session concept, so cross-account enforcement cannot live inside `triage_submission(...)` itself. It should be enforced at the service/data-access boundary if this engine is deployed.

Recommended deployment controls:

- Authenticate caller before accepting a submission.
- Authorize access to the patient/case server-side using tenant/account membership.
- Derive tenant/account scope from trusted auth context, not request JSON.
- Fetch patient submissions by `(tenant_id, case_id)` or equivalent scoped key.
- Prevent IDOR/BOLA by denying direct object access to cross-tenant patient IDs, MRNs, case IDs, and document IDs.
- Keep evaluator/debug reports out of shared locations unless access-controlled.
- Avoid logging full submissions, document text, MRNs, names, DOBs, or generated evidence excerpts unless explicitly required.
- If evidence must be shown, show it only to authorized users with a need to know.
- Add audit logs for access to patient cases and generated triage outputs.

Current code-level privacy controls:

- The rule engine does not include patient ID, MRN, name, DOB, or sex in normal issue output because policy decisions do not depend on demographics.
- Missing-document and missing-lab messages summarize document/lab types and dates instead of copying patient demographics.
- Generated eval artifacts are ignored by git.
- No external API receives patient-like data.

Important tradeoff: the assignment requires every issue to include exact field values, dates, or document excerpts used as evidence. In production, evidence display/logging should be role-gated and possibly redacted depending on downstream audience.

## Pentest finding remediation matrix

| Finding | Fix |
| --- | --- |
| `NaN` / future-dated vitals suppress acute BP/temp exclusions | `_latest_vital(...)` ignores future-dated vitals relative to `metadata.submission_received_at` and ignores non-finite values such as `NaN`/`inf`. Older valid acute vitals can still trigger `NOT_CLEARED`. |
| Forged consent/H&P via bare keyword match | H&P and consent classification require document-type signals; arbitrary note text containing keywords no longer satisfies documentation gates. |
| Cancelled/fake-code labs like `NOT-CBC` satisfy CBC/CMP gates | `_is_lab(...)` tokenizes lab codes, rejects `NOT-`/fake/cancelled indicators, and requires acceptable final-like status. |
| Anticoagulation plan keyword/negation bypass | Ambiguous/negated language is checked before hold/resume keyword acceptance. |
| Client-controlled `procedure_risk` downgrade skips CMP | `_effective_procedure_risk(...)` conservatively upgrades to `HIGH` if procedure text/documents indicate high risk. |
| Full PHI duplicated into baseline/eval artifacts | Baseline outputs store case ID, output, and submission fingerprint, not full submission; eval reports omit full submissions. |
| `make evals` sends case data to OpenAI despite no-API docs | `make evals` is local-only; OpenAI Eval requires explicit `make openai-evals` / `--openai-eval`. |
| Unrestricted `--output` / `--report` symlink overwrite | Output/report paths must resolve inside repo and cannot overwrite symlinks. |
| Unbounded JSONL/text/`--runs` resource exhaustion | JSONL file size, line size, record count, and determinism run count are bounded. |
| Rich markup injection in TUI | TUI interpolated report fields are escaped before rendering as Rich markup. |
| `record_index`-only join corrupts scores | Eval validates baseline `case_id` and submission fingerprint before scoring a row. |
| No patient/case binding | Baseline rows include case ID plus submission fingerprint; eval rejects mismatched rows before metrics are computed. |

## Security-focused tests

Current tests include:

- Deterministic output for identical submissions.
- Prompt-injection-style clinical note cannot control decision.
- “Not a consent” text cannot satisfy consent requirement.
- Unknown anticoagulant active status fails closed as `MISSING_REQUIRED_DATA`.
- Unclear anticoagulation plans are rejected.
- Acute safety exclusion overrides follow-up issues.
- Unrelated patient identifiers/demographics are not copied into output for issues that do not require them as evidence.
- Pentest regression tests for NaN/future vitals, forged docs, fake labs, anticoagulation negation, risk downgrades, artifact redaction, safe paths, TUI escaping, and case binding.

Useful future tests if this becomes an API/service:

- Oversized payload limits.
- Malformed JSON and schema rejection.
- PHI-safe logging assertions.
- Dependency vulnerability scan in CI.
- AuthZ tests for tenant/patient separation.
- Fuzz tests for date parsing and document text variants.

## Known limitations

- This is not a complete HIPAA/security compliance program.
- No authentication, authorization, encryption-at-rest, audit logging, or tenant isolation is implemented because the starter is a local CLI/eval harness.
- Evidence details may include document excerpts from patient-like text. In production, downstream logs and reports should minimize or redact these fields where possible.
