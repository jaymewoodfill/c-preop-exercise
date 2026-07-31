#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

INPUT="${INPUT:-data/patients_sample_50.jsonl}"
OUTPUT="${OUTPUT:-data/baseline_outputs.jsonl}"
REPORT="${REPORT:-data/eval_report.json}"
DETERMINISM_REPORT="${DETERMINISM_REPORT:-data/determinism_report.json}"
MODEL="${MODEL:-unused}"
RUNS="${RUNS:-10}"
RECORD_INDEX="${RECORD_INDEX:-0}"

step() {
  printf '\n==> %s\n' "$1"
}

step "Checking lockfile"
uv lock --check

step "Running lint"
uv run --extra dev ruff check .

step "Running tests"
uv run --extra dev python -m pytest tests

step "Generating baseline outputs"
uv run run_baseline.py \
  --input "$INPUT" \
  --output "$OUTPUT" \
  --model "$MODEL"

step "Running local eval"
uv run run_evals.py \
  --input "$INPUT" \
  --outputs "$OUTPUT" \
  --report "$REPORT"

step "Running determinism check"
uv run run_evals.py \
  --determinism \
  --input "$INPUT" \
  --model "$MODEL" \
  --report "$DETERMINISM_REPORT" \
  --runs "$RUNS" \
  --record-index "$RECORD_INDEX"

step "Summary"
python3 - <<'PY'
import json
from pathlib import Path

eval_report = json.loads(Path("data/eval_report.json").read_text())
determinism_report = json.loads(Path("data/determinism_report.json").read_text())

print("Score:", eval_report.get("primary_score"))
print("Local metrics:", eval_report.get("local_metrics_summary"))
print(
    "Determinism:",
    {
        key: determinism_report.get(key)
        for key in (
            "decision_stability_pct",
            "json_format_stability_pct",
            "exact_output_match_pct",
        )
    },
)
PY

printf '\n✅ Validation complete\n'
