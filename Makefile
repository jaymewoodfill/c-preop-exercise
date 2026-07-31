INPUT ?= data/patients_sample_50.jsonl
OUTPUT ?= data/baseline_outputs.jsonl
REPORT ?= data/eval_report.json
DETERMINISM_REPORT ?= data/determinism_report.json
MODEL ?= gpt-4.1-mini

.PHONY: baseline evals openai-evals determinism score report lint test security-test policy-test pentest-test auth-test validate all clean

baseline:
	uv run run_baseline.py \
		--input $(INPUT) \
		--output $(OUTPUT) \
		--model $(MODEL)

evals:
	uv run run_evals.py \
		--input $(INPUT) \
		--outputs $(OUTPUT) \
		--report $(REPORT)

openai-evals:
	uv run --with 'openai==2.52.0' run_evals.py \
		--openai-eval \
		--input $(INPUT) \
		--outputs $(OUTPUT) \
		--report $(REPORT)

determinism:
	uv run run_evals.py \
		--determinism \
		--input $(INPUT) \
		--model $(MODEL) \
		--report $(DETERMINISM_REPORT)

score:
	@python3 -c 'import json; r=json.load(open("$(REPORT)")); s=(r.get("primary_score",{}) or {}).get("value_pct"); print(s if s is not None else r.get("local_metrics_summary",{}).get("aggregate_local_score_pct", 0.0))'

report:
	uv run view_report.py --report $(REPORT)

lint:
	uv run --extra dev ruff check .

test:
	uv run --extra dev python -m pytest tests

security-test:
	uv run --extra dev python -m pytest tests/test_security_regression.py

policy-test:
	uv run --extra dev python -m pytest tests/test_policy_boundaries.py

pentest-test:
	uv run --extra dev python -m pytest tests/test_pentest_regression.py

auth-test:
	uv run --extra dev python -m pytest tests/test_auth.py

validate:
	./validate.sh

all: baseline evals determinism score

clean:
	rm -f data/baseline_outputs.jsonl \
		data/eval_report.json \
		data/determinism_report.json
