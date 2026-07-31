# Submission Summary

## What changed from the starter

The starter implementation made a single LLM call. I replaced that with a deterministic policy engine because the supplied Cadence policy is explicit, finite, and safety-sensitive.

Key changes:

- Deterministic `triage_submission(...)` implementation.
- Modularized code into focused files:
  - `models.py` — Pydantic schemas and type aliases.
  - `rules.py` — policy rule engine.
  - `evidence.py` — issue/evidence/explanation builders.
  - `parsing.py` — date/number/text parsing helpers.
  - `core.py` — compatibility re-export for the starter API.
- Local-only eval path by default; OpenAI Eval is explicit opt-in.
- Security, privacy, pentest, auth, and HIPAA-aligned documentation.
- CI workflow, lint config, dependency pins, and lockfile.

## How to run

Preferred one-command validation:

```bash
./validate.sh
```

or:

```bash
make validate
```

Manual commands:

```bash
make test
make baseline MODEL=unused
make evals
make determinism MODEL=unused
make score
```

If `make` is unavailable, use `./validate.sh` or run commands directly:

```bash
uv run --extra dev python -m pytest tests
uv run run_baseline.py --input data/patients_sample_50.jsonl --output data/baseline_outputs.jsonl --model unused
uv run run_evals.py --input data/patients_sample_50.jsonl --outputs data/baseline_outputs.jsonl --report data/eval_report.json
uv run run_evals.py --determinism --input data/patients_sample_50.jsonl --model unused --report data/determinism_report.json --runs 10 --record-index 0
python3 -c 'import json; print(json.load(open("data/eval_report.json"))["primary_score"])'
```

Optional OpenAI Eval run, if intentionally desired:

```bash
make openai-evals
```

## Validation results

Latest local validation:

- Lint: passing.
- Tests: `48 passed`.
- Eval score: `100.0%`.
- Decision match: `100.0%`.
- Issue category match: `100.0%`.
- Evidence grounding: `100.0%`.
- Determinism exact output match: `100.0%`.

## Security and privacy highlights

- No runtime LLM/API call in default workflows.
- No OpenAI API key required for baseline/eval/determinism.
- Clinical note text treated as untrusted evidence, not instructions.
- Prompt-injection-style text cannot override policy decisions.
- Missing/unknown required data fails closed to `NEEDS_FOLLOW_UP`.
- Acute safety exclusions dominate decision as `NOT_CLEARED`.
- Baseline/eval artifacts omit full submissions and use submission fingerprints.
- Rich markup in report fields is escaped before TUI rendering.
- Output/report paths are constrained to repo and symlink overwrite is rejected.
- JSONL size and determinism runs are bounded.
- Optional `auth.py` demonstrates signed-token, scope, and tenant checks before triage.
- HIPAA-aligned privacy notes document Minimum Necessary, audit, retention, third-party disclosure, and access-control considerations without claiming HIPAA compliance.

## Pentest regressions addressed

Covered by `tests/test_pentest_regression.py`:

- `NaN` / future-dated vitals cannot suppress acute exclusions.
- Bare keywords cannot forge consent or H&P documents.
- Fake/cancelled lab codes such as `NOT-CBC` do not satisfy testing gates.
- Anticoagulation plan keyword/negation bypasses are rejected.
- Client-controlled `procedure_risk` downgrade does not skip high-risk CMP when high-risk evidence is present.
- Generated artifacts avoid full PHI duplication.
- Local eval no longer sends case data to OpenAI by default.
- Unsafe output/report paths and symlink overwrites are rejected.
- TUI markup injection is escaped.
- Baseline rows are bound by case ID and submission fingerprint.

## Known limitations

- This is not a medical guideline engine beyond the supplied assignment policy.
- This is not a HIPAA compliance implementation.
- `auth.py` is a boundary demonstration, not a replacement for production identity infrastructure.
- No production database, audit logging, encryption-at-rest, or deployment layer is implemented.
- Document classification is deterministic/heuristic and intentionally scoped to the assignment.
- Evidence may include clinical excerpts where the assignment requires exact supporting details; production display/logging should be role-gated and minimized.
