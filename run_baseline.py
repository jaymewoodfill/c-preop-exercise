#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydantic>=2.8.0",
# ]
# ///

"""Run a baseline triage model on prepared pre-op submission packages."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from core import (
    PatientSubmission,
    triage_submission,
)

ROOT = Path(__file__).resolve().parent

DEFAULT_MODEL = "gpt-4.1-mini"
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 10_000


@dataclass
class BaselineInputCase:
    case_id: str
    submission: PatientSubmission


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=str(ROOT / "data" / "patients_sample_50.jsonl"),
        help="Input patient JSONL file",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "data" / "baseline_outputs.jsonl"),
        help="Output JSONL file with model responses",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Model id placeholder preserved for starter CLI compatibility",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Maximum number of records to process (0 means all)",
    )
    return parser.parse_args()


def _safe_output_path(raw_path: str) -> Path:
    path = Path(raw_path)
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"Output path must stay inside repository: {raw_path}")
    if path.exists() and path.is_symlink():
        raise ValueError(f"Refusing to overwrite symlink output path: {raw_path}")
    return resolved


def _submission_fingerprint(submission: dict[str, Any]) -> str:
    canonical = json.dumps(submission, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_cases(path: Path) -> list[BaselineInputCase]:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"Input file too large: {path}")

    cases: list[BaselineInputCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ValueError(f"Input row {idx} exceeds maximum line size")
            if idx >= MAX_RECORDS:
                raise ValueError(f"Input exceeds maximum record count ({MAX_RECORDS})")
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if (
                isinstance(payload, dict)
                and "submission" in payload
                and "case_id" in payload
            ):
                case = BaselineInputCase(
                    case_id=str(payload["case_id"]),
                    submission=PatientSubmission.model_validate(payload["submission"]),
                )
            else:
                case = BaselineInputCase(
                    case_id=f"case_{idx:05d}",
                    submission=PatientSubmission.model_validate(payload),
                )
            cases.append(case)
    return cases


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    output_path = _safe_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cases = load_cases(input_path)
    if args.max_records > 0:
        cases = cases[: args.max_records]

    with output_path.open("w", encoding="utf-8") as handle:
        for idx, case in enumerate(cases):
            print(f"[{idx + 1}/{len(cases)}] Running baseline inference")
            submission = case.submission.model_dump()
            row: dict[str, Any] = {
                "record_index": idx,
                "case_id": case.case_id,
                "submission_fingerprint": _submission_fingerprint(submission),
                "model": args.model,
                "output": None,
                "error": None,
            }

            try:
                output = triage_submission(
                    submission=submission,
                    model=args.model,
                )
                row["output"] = output.model_dump()
            except Exception as exc:  # pragma: no cover - network/runtime failure path
                row["error"] = str(exc)

            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")

    print(f"Wrote baseline outputs -> {output_path}")


if __name__ == "__main__":
    main()
