"""Compatibility module for the pre-op triage starter API.

The implementation is split across focused modules:
- models.py: Pydantic schemas and type aliases
- rules.py: deterministic policy engine
- llm_prompt.py: legacy prompt helpers retained for starter compatibility
"""

from __future__ import annotations

from llm_prompt import BASELINE_SYSTEM_PROMPT, build_user_prompt
from models import (
    BloodPressureVital,
    Condition,
    Decision,
    Document,
    GenericVital,
    IssueCategory,
    LabResult,
    Medication,
    PatientInfo,
    PatientName,
    PatientSubmission,
    PreparedPatientCase,
    ProcedureInfo,
    ProcedureRisk,
    SubmissionMetadata,
    TemperatureVital,
    TriageIssue,
    TriageIssueEvidence,
    TriageOutput,
    Vital,
    triage_output_json_schema,
)
from rules import triage_submission

__all__ = [
    "BASELINE_SYSTEM_PROMPT",
    "BloodPressureVital",
    "Condition",
    "Decision",
    "Document",
    "GenericVital",
    "IssueCategory",
    "LabResult",
    "Medication",
    "PatientInfo",
    "PatientName",
    "PatientSubmission",
    "PreparedPatientCase",
    "ProcedureInfo",
    "ProcedureRisk",
    "SubmissionMetadata",
    "TemperatureVital",
    "TriageIssue",
    "TriageIssueEvidence",
    "TriageOutput",
    "Vital",
    "build_user_prompt",
    "triage_output_json_schema",
    "triage_submission",
]
