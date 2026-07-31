"""Shared policy, schema, and prompt helpers for the pre-op triage scripts."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

# -------------------------
# Policy + system prompt
# -------------------------

BASELINE_SYSTEM_PROMPT = """
You are a clinical operations assistant for pre-op scheduling triage.
Use only the policy below. Do not use outside medical knowledge.

Cadence Surgical Center Pre-Operative Scheduling Policy (effective Jan 1, 2026)

Output exactly one status:
- READY
- NEEDS_FOLLOW_UP
- NOT_CLEARED

Rule 1: Required documentation
- History and Physical (H&P) must exist and be completed within 30 days of procedure date.
- Signed Surgical Consent must exist.
If documentation is missing/outdated -> NEEDS_FOLLOW_UP.

Rule 2: Required testing by procedure risk
- LOW or MODERATE risk: CBC within 30 days of procedure date.
- HIGH risk: CBC within 14 days and CMP within 14 days.
Use only the most recent result for each required test.
If a required test is missing or outside window -> NEEDS_FOLLOW_UP.

Rule 3: Anticoagulation management
If the patient is currently taking an anticoagulant, a perioperative anticoagulation plan must be documented and clear.
If no clear plan is documented -> NEEDS_FOLLOW_UP.

Rule 4: Acute safety exclusions
If any of the following are present at review time -> NOT_CLEARED:
- Systolic BP >= 180 mmHg
- Diastolic BP >= 110 mmHg
- Temperature > 100.4 F
Use the most recent relevant vital.

Final determination
- READY only if all required criteria are satisfied and no exclusions are present.
- If a required field needed to evaluate a rule is missing/unknown -> NEEDS_FOLLOW_UP.

Output requirements
- Return exactly one JSON object.
""".strip()

Decision = Literal["READY", "NEEDS_FOLLOW_UP", "NOT_CLEARED"]
ProcedureRisk = Literal["LOW", "MODERATE", "HIGH"]
IssueCategory = Literal[
    "REQUIRED_DOCUMENTATION",
    "REQUIRED_TESTING",
    "ANTICOAGULATION_MANAGEMENT",
    "ACUTE_SAFETY_EXCLUSION",
    "MISSING_REQUIRED_DATA",
]

# -------------------------
# Schemas
# -------------------------

class PatientName(BaseModel):

    given: str | None = None
    family: str | None = None

class PatientInfo(BaseModel):

    id: str | None = None
    mrn: str | None = None
    name: PatientName | None = None
    dob: str | None = None
    sex: str | None = None

class ProcedureInfo(BaseModel):

    case_id: str | None = None
    procedure_type: str | None = None
    procedure_risk: ProcedureRisk | None = None
    procedure_date: str | None = None
    is_elective: bool | None = None
    location: str | None = None

class BloodPressureVital(BaseModel):

    type: str | None = None
    systolic: float | int | None = None
    diastolic: float | int | None = None
    date: str | None = None
    source: str | None = None

class TemperatureVital(BaseModel):

    type: str | None = None
    value_f: float | int | None = None
    date: str | None = None
    source: str | None = None

class GenericVital(BaseModel):

    type: str | None = None
    date: str | None = None
    source: str | None = None

Vital = BloodPressureVital | TemperatureVital | GenericVital

class LabResult(BaseModel):

    id: str | None = None
    code: str | None = None
    display: str | None = None
    effective_at: str | None = None
    status: str | None = None
    source: str | None = None

class Medication(BaseModel):

    name: str | None = None
    active: bool | None = None

class Condition(BaseModel):

    name: str | None = None
    active: bool | None = None

class Document(BaseModel):

    doc_id: str | None = None
    type: str | None = None
    date: str | None = None
    author: str | None = None
    text: str | None = None

class SubmissionMetadata(BaseModel):

    submission_received_at: str | None = None
    source_system: str | None = None

class PatientSubmission(BaseModel):
    """Single submission package shape from the take-home prompt."""

    patient: PatientInfo | None = None
    procedure: ProcedureInfo | None = None
    vitals: list[Vital] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)
    metadata: SubmissionMetadata | None = None

class TriageIssueEvidence(BaseModel):

    source: str
    details: str

class TriageIssue(BaseModel):

    category: IssueCategory
    description: str
    evidence: TriageIssueEvidence

class TriageOutput(BaseModel):
    """Structured output contract for triage responses."""

    decision: Decision
    issues: list[TriageIssue] = Field(validation_alias=AliasChoices("issues"))
    explanation: str


class PreparedPatientCase(BaseModel):
    """Serialized eval case with submission payload and expected oracle output."""

    case_id: str
    submission: PatientSubmission
    expected_output: TriageOutput


def triage_output_json_schema() -> dict[str, object]:
    """Return the JSON schema used for structured model outputs."""

    schema = TriageOutput.model_json_schema()
    return schema


# -------------------------
# Prompt helpers
# -------------------------


def build_user_prompt(submission: dict[str, object]) -> str:
    """Format a single submission package as user input."""

    sections = [
        "Evaluate this patient package for pre-op scheduling readiness using the provided policy.",
        "Return your response as JSON.",
        "Submission JSON:",
        json.dumps(submission, sort_keys=True),
    ]
    return "\n".join(sections)


# Static list is intentionally small and policy-adjacent: enough to detect sample
# anticoagulants without importing external medical guidelines.
ANTICOAGULANTS = {
    "apixaban",
    "eliquis",
    "warfarin",
    "coumadin",
    "rivaroxaban",
    "xarelto",
    "dabigatran",
    "pradaxa",
    "edoxaban",
    "savaysa",
    "enoxaparin",
    "lovenox",
    "heparin",
}

# Negated/vague language must win over keyword matches like "hold"/"resume" so
# notes such as "no clear hold/resume guidance" fail closed.
AMBIGUOUS_PLAN_TERMS = (
    "no clear",
    "not yet documented",
    "pending",
    "await",
    "follow up",
    "follow-up",
    "refer",
    "specialist input",
    "recommendations",
    "to be determined",
    "tbd",
    "unclear",
    "no guidance",
    "no instructions",
    "not documented",
    "not agreed",
    "could not agree",
    "cannot agree",
    "unable to agree",
    "not finalized",
)

PREOP_PLAN_TERMS = ("hold", "stop", "pause", "withhold", "last dose", "do not take")
POSTOP_PLAN_TERMS = ("resume", "restart", "re-start", "post-op", "postoperative", "post-operative", "after surgery")


def triage_submission(
    submission: dict[str, object] | PatientSubmission,
    *,
    model: str,
) -> TriageOutput:
    """Deterministic policy engine for one pre-op submission.

    `model` is accepted to preserve the starter API used by the harness.
    """

    # Validate at the boundary, then keep the core side-effect-free. This gives
    # deterministic behavior and avoids sending patient-like data to an LLM/API.
    if isinstance(submission, PatientSubmission):
        payload = submission.model_dump()
    else:
        payload = PatientSubmission.model_validate(submission).model_dump()

    issues: list[TriageIssue] = []
    procedure = _as_dict(payload.get("procedure"))
    procedure_date_raw = procedure.get("procedure_date")
    procedure_date = _parse_date(procedure_date_raw)
    procedure_risk = procedure.get("procedure_risk")
    metadata = _as_dict(payload.get("metadata"))
    review_datetime = _parse_datetime(metadata.get("submission_received_at"))

    # Structured procedure date is treated as authoritative; document text may
    # mention target dates, but inferring from free text would hide missing data.
    if procedure_date_raw in (None, ""):
        issues.append(_issue("MISSING_REQUIRED_DATA", "Missing procedure date", "procedure.procedure_date", "procedure.procedure_date is null"))
    elif procedure_date is None:
        issues.append(_issue("MISSING_REQUIRED_DATA", "Invalid procedure date", "procedure.procedure_date", f"procedure.procedure_date={procedure_date_raw!r} is not a valid date"))

    if procedure_risk is None:
        issues.append(_issue("MISSING_REQUIRED_DATA", "Missing procedure risk", "procedure.procedure_risk", "procedure.procedure_risk is null"))

    documents = _as_list(payload.get("documents"))
    labs = _as_list(payload.get("labs"))
    vitals = _as_list(payload.get("vitals"))
    medications = _as_list(payload.get("medications"))
    effective_procedure_risk = _effective_procedure_risk(procedure_risk, procedure, documents)

    if procedure_date is not None:
        issues.extend(_documentation_issues(documents, procedure_date))
    else:
        # Without a procedure date, freshness windows cannot be evaluated, but
        # presence issues are still useful operational blockers.
        issues.extend(_documentation_presence_issues(documents))

    if procedure_date is not None and effective_procedure_risk in {"LOW", "MODERATE", "HIGH"}:
        issues.extend(_testing_issues(labs, procedure_date, effective_procedure_risk))

    anticoagulants, unknown_anticoagulants = _anticoagulant_medications(medications)
    for med_name, index in unknown_anticoagulants:
        issues.append(
            _issue(
                "MISSING_REQUIRED_DATA",
                "Unknown anticoagulant active status",
                f"medications[{index}]",
                f"Medication {med_name} has active=null; cannot determine if currently taking",
            )
        )
    if anticoagulants:
        anticoag_issue = _anticoagulation_issue(anticoagulants, documents)
        if anticoag_issue is not None:
            issues.append(anticoag_issue)

    issues.extend(_vital_issues(vitals, review_datetime))

    # Safety exclusions dominate scheduling readiness, while retaining other
    # follow-up issues in the response for operational visibility.
    if any(issue.category == "ACUTE_SAFETY_EXCLUSION" for issue in issues):
        decision: Decision = "NOT_CLEARED"
    elif issues:
        decision = "NEEDS_FOLLOW_UP"
    else:
        decision = "READY"

    return TriageOutput(decision=decision, issues=issues, explanation=_explanation(issues))


def _issue(category: IssueCategory, description: str, source: str, details: str) -> TriageIssue:
    return TriageIssue(category=category, description=description, evidence=TriageIssueEvidence(source=source, details=details))


def _explanation(issues: list[TriageIssue]) -> str:
    if not issues:
        return "All required criteria are satisfied."
    return " | ".join(f"{issue.category}: {issue.description}" for issue in issues)


def _documentation_presence_issues(documents: list[dict[str, Any]]) -> list[TriageIssue]:
    # Used when procedure_date is missing: report missing docs, but avoid
    # pretending we can evaluate 30-day freshness without the anchor date.
    issues: list[TriageIssue] = []
    hp_docs = [(doc, i, _parse_date(doc.get("date"))) for i, doc in enumerate(documents) if _is_hp_document(doc)]
    consent_docs = [(doc, i) for i, doc in enumerate(documents) if _is_consent_document(doc)]
    if not any(doc_date is not None for _, _, doc_date in hp_docs):
        issues.append(_issue("REQUIRED_DOCUMENTATION", "History and Physical document missing", "documents", f"No History and Physical document with valid date found; documents include: {_document_summary(documents)}"))
    if not consent_docs:
        issues.append(_issue("REQUIRED_DOCUMENTATION", "Signed surgical consent missing", "documents", f"No Surgical Consent document found; documents include: {_document_summary(documents)}"))
    else:
        unsigned = _first_unsigned_consent(consent_docs)
        if unsigned is not None:
            doc, index = unsigned
            issues.append(_issue("REQUIRED_DOCUMENTATION", "Surgical consent not clearly signed", f"documents[{index}]", f"Consent document text does not clearly indicate signed consent: {_excerpt(doc.get('text'))}"))
    return issues


def _documentation_issues(documents: list[dict[str, Any]], procedure_date: date) -> list[TriageIssue]:
    issues: list[TriageIssue] = []
    hp_docs = [(doc, i, _parse_date(doc.get("date"))) for i, doc in enumerate(documents) if _is_hp_document(doc)]
    valid_hp_docs = [(doc, i, doc_date) for doc, i, doc_date in hp_docs if doc_date is not None]
    if not valid_hp_docs:
        issues.append(_issue("REQUIRED_DOCUMENTATION", "History and Physical document missing", "documents", f"No History and Physical document with valid date found; documents include: {_document_summary(documents)}"))
    else:
        doc, index, doc_date = max(valid_hp_docs, key=lambda item: (item[2], -item[1]))
        days_prior = (procedure_date - doc_date).days
        if days_prior < 0 or days_prior > 30:
            issues.append(
                _issue(
                    "REQUIRED_DOCUMENTATION",
                    "H&P outside 30-day window",
                    f"documents[{index}]",
                    f"H&P date {doc_date.isoformat()} vs procedure_date {procedure_date.isoformat()} ({days_prior} days prior; must be within 30)",
                )
            )

    consent_docs = [(doc, i) for i, doc in enumerate(documents) if _is_consent_document(doc)]
    if not consent_docs:
        issues.append(_issue("REQUIRED_DOCUMENTATION", "Signed surgical consent missing", "documents", f"No Surgical Consent document found; documents include: {_document_summary(documents)}"))
    else:
        unsigned = _first_unsigned_consent(consent_docs)
        if unsigned is not None:
            doc, index = unsigned
            issues.append(_issue("REQUIRED_DOCUMENTATION", "Surgical consent not clearly signed", f"documents[{index}]", f"Consent document text does not clearly indicate signed consent: {_excerpt(doc.get('text'))}"))
    return issues


def _testing_issues(labs: list[dict[str, Any]], procedure_date: date, procedure_risk: str) -> list[TriageIssue]:
    issues: list[TriageIssue] = []
    requirements = [("CBC", 30)] if procedure_risk in {"LOW", "MODERATE"} else [("CBC", 14), ("CMP", 14)]
    for lab_code, max_days in requirements:
        matching = [(lab, i, _parse_date(lab.get("effective_at"))) for i, lab in enumerate(labs) if _is_lab(lab, lab_code)]
        valid = [(lab, i, lab_date) for lab, i, lab_date in matching if lab_date is not None]
        if not valid:
            issues.append(
                _issue(
                    "REQUIRED_TESTING",
                    f"{lab_code} missing",
                    "labs",
                    f"No {lab_code} result with valid effective_at found for procedure_risk {procedure_risk}; labs include: {_lab_summary(labs)}",
                )
            )
            continue
        # Policy says only the most recent result for each required test counts.
        lab, index, lab_date = max(valid, key=lambda item: (item[2], -item[1]))
        days_prior = (procedure_date - lab_date).days
        if days_prior < 0 or days_prior > max_days:
            issues.append(
                _issue(
                    "REQUIRED_TESTING",
                    f"{lab_code} outside {max_days}-day window for {procedure_risk} risk procedure",
                    f"labs[{index}]",
                    f"{lab_code} effective_at {lab.get('effective_at')} vs procedure_date {procedure_date.isoformat()} ({days_prior} days prior; must be within {max_days})",
                )
            )
    return issues


def _anticoagulation_issue(active_anticoagulants: list[tuple[str, int]], documents: list[dict[str, Any]]) -> TriageIssue | None:
    # Free-text documents are untrusted evidence, not instructions. The engine
    # only extracts narrow policy signals and rejects ambiguous plan language.
    med_refs = ", ".join(f"medications[{index}]" for _, index in active_anticoagulants)
    med_names = [name.lower() for name, _ in active_anticoagulants]
    best_source = "documents"
    best_excerpt = ""
    for index, doc in enumerate(documents):
        text = _document_text(doc).lower()
        mentions_med = any(name and name in text for name in med_names)
        mentions_anticoag = "anticoag" in text or "blood thinner" in text
        mentions_plan = any(term in text for term in ("periop", "peri-op", "perioperative", "procedure", "surgery", "anticoag plan", "medication plan", "blood thinner"))
        if (mentions_med or mentions_anticoag) and mentions_plan:
            best_source = f"documents[{index}]"
            best_excerpt = _excerpt(doc.get("text"))
            if _is_clear_anticoagulation_plan(text):
                return None
    details = f"Active anticoagulant medication present ({med_refs}) but no clear perioperative plan document found"
    if best_source != "documents":
        details = f"{details}; document excerpt: {best_excerpt}"
    return _issue("ANTICOAGULATION_MANAGEMENT", "Missing perioperative anticoagulation plan", best_source, details)


def _vital_issues(vitals: list[dict[str, Any]], review_datetime: datetime | None) -> list[TriageIssue]:
    issues: list[TriageIssue] = []
    latest_bp = _latest_vital(vitals, "blood_pressure", review_datetime)
    latest_temp = _latest_vital(vitals, "temperature", review_datetime)

    if latest_bp is None:
        issues.append(_issue("MISSING_REQUIRED_DATA", "Missing latest blood pressure", "vitals", "No blood_pressure vital with valid date found"))
    else:
        vital, index = latest_bp
        systolic = vital.get("systolic")
        diastolic = vital.get("diastolic")
        if _number(systolic) is None or _number(diastolic) is None:
            issues.append(_issue("MISSING_REQUIRED_DATA", "Missing latest blood pressure", f"vitals[{index}]", f"latest BP systolic={systolic}, diastolic={diastolic}; both values are required"))
        elif _number(systolic) >= 180 or _number(diastolic) >= 110:
            issues.append(
                _issue(
                    "ACUTE_SAFETY_EXCLUSION",
                    "Blood pressure meets exclusion threshold",
                    f"vitals[{index}]",
                    f"latest BP systolic={_format_number(systolic)}, diastolic={_format_number(diastolic)} on {vital.get('date')}; threshold systolic>=180 or diastolic>=110",
                )
            )

    if latest_temp is None:
        issues.append(_issue("MISSING_REQUIRED_DATA", "Missing latest temperature", "vitals", "No temperature vital with valid date found"))
    else:
        vital, index = latest_temp
        value_f = vital.get("value_f")
        if _number(value_f) is None:
            issues.append(_issue("MISSING_REQUIRED_DATA", "Missing latest temperature", f"vitals[{index}]", f"latest temperature value_f={value_f}; value_f is required"))
        elif _number(value_f) > 100.4:
            issues.append(
                _issue(
                    "ACUTE_SAFETY_EXCLUSION",
                    "Temperature exceeds exclusion threshold",
                    f"vitals[{index}]",
                    f"latest temperature value_f={_format_number(value_f)} on {vital.get('date')}; threshold is > 100.4",
                )
            )

    return issues


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [item if isinstance(item, dict) else {} for item in value] if isinstance(value, list) else []


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_date(value: Any) -> date | None:
    parsed = _parse_datetime(value)
    return parsed.date() if parsed is not None else None


def _document_text(doc: dict[str, Any]) -> str:
    return "\n".join(str(part) for part in (doc.get("type"), doc.get("text"), doc.get("author")) if part)


def _is_hp_document(doc: dict[str, Any]) -> bool:
    doc_type = _normalized_text(doc.get("type"))
    # Require the document type to look like an H&P. Bare keywords in arbitrary
    # note text are too easy to forge and should not satisfy documentation gates.
    type_terms = (
        "history and physical",
        "history & physical",
        "physical examination",
        "h&p",
        "h and p",
        "hist & phys",
        "hx & physical",
    )
    return any(term in doc_type for term in type_terms)


def _is_consent_document(doc: dict[str, Any]) -> bool:
    doc_type = _normalized_text(doc.get("type"))
    text = _normalized_text(doc.get("text"))
    if "not a consent" in text:
        # Prevent false positives from adversarial or clarifying note text.
        return False
    # Require a consent-like document type; arbitrary notes with "signed consent"
    # in the body are treated as evidence at most, not as the required document.
    return "consent" in doc_type


def _first_unsigned_consent(consent_docs: list[tuple[dict[str, Any], int]]) -> tuple[dict[str, Any], int] | None:
    for doc, index in consent_docs:
        text = _document_text(doc).lower()
        if "unsigned" in text or "awaiting patient signature" in text or "signature not yet" in text:
            return doc, index
        if "signed" not in text and "signature" not in text:
            return doc, index
    return None


def _document_summary(documents: list[dict[str, Any]], limit: int = 4) -> str:
    # Summaries ground missing-document issues without echoing unrelated patient
    # identifiers such as MRN/name into output.
    if not documents:
        return "none"
    parts = []
    for index, doc in enumerate(documents[:limit]):
        parts.append(f"documents[{index}] type={doc.get('type')!r} date={doc.get('date')!r}")
    return "; ".join(parts)


def _lab_summary(labs: list[dict[str, Any]], limit: int = 4) -> str:
    if not labs:
        return "none"
    parts = []
    for index, lab in enumerate(labs[:limit]):
        parts.append(f"labs[{index}] code={lab.get('code')!r} effective_at={lab.get('effective_at')!r}")
    return "; ".join(parts)


def _is_lab(lab: dict[str, Any], code: str) -> bool:
    status = _normalized_text(lab.get("status"))
    if status and status not in {"final", "corrected", "amended"}:
        return False

    lab_code = str(lab.get("code") or "").upper().strip()
    display = _normalized_text(lab.get("display"))
    if any(term in f"{lab_code} {display}" for term in ("CANCEL", "NOT-", "FAKE", "VOID", "ERRONEOUS")):
        return False

    tokens = {token for token in re.split(r"[^A-Z0-9]+", lab_code) if token}
    if code == "CBC":
        return "CBC" in tokens or "complete blood count" in display
    return "CMP" in tokens or "comprehensive metabolic panel" in display


def _anticoagulant_medications(medications: list[dict[str, Any]]) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    active: list[tuple[str, int]] = []
    unknown: list[tuple[str, int]] = []
    for index, med in enumerate(medications):
        name = str(med.get("name") or "")
        if not any(term in name.lower() for term in ANTICOAGULANTS):
            continue
        if med.get("active") is True:
            active.append((name, index))
        elif med.get("active") is None:
            unknown.append((name, index))
    return active, unknown


def _is_clear_anticoagulation_plan(text: str) -> bool:
    text = _normalized_text(text)
    if any(term in text for term in AMBIGUOUS_PLAN_TERMS):
        return False
    # Require both pre-op and post-op management language; a partial plan is not
    # enough to satisfy the policy requirement for clear perioperative management.
    return any(term in text for term in PREOP_PLAN_TERMS) and any(term in text for term in POSTOP_PLAN_TERMS)


def _latest_vital(vitals: list[dict[str, Any]], vital_type: str, review_datetime: datetime | None) -> tuple[dict[str, Any], int] | None:
    # Acute safety rules use only the latest relevant vital. Future-dated rows and
    # non-finite values cannot safely establish current review state.
    valid: list[tuple[dict[str, Any], int, datetime]] = []
    for index, vital in enumerate(vitals):
        if str(vital.get("type") or "").lower() != vital_type:
            continue
        vital_date = _parse_datetime(vital.get("date"))
        if vital_date is None:
            continue
        if review_datetime is not None and vital_date > review_datetime:
            continue
        if vital_type == "blood_pressure" and (_number(vital.get("systolic")) is None or _number(vital.get("diastolic")) is None):
            continue
        if vital_type == "temperature" and _number(vital.get("value_f")) is None:
            continue
        valid.append((vital, index, vital_date))
    if not valid:
        return None
    vital, index, _ = max(valid, key=lambda item: (item[2], -item[1]))
    return vital, index


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def _effective_procedure_risk(procedure_risk: str | None, procedure: dict[str, Any], documents: list[dict[str, Any]]) -> str | None:
    risk = procedure_risk
    risk_text = " ".join(
        [_normalized_text(procedure.get("procedure_type"))]
        + [_normalized_text(doc.get("type")) + " " + _normalized_text(doc.get("text")) for doc in documents]
    )
    # If any submitted materials describe the case as high risk, conservatively
    # apply the stricter HIGH testing gate even if the structured field is lower.
    if re.search(r"\bhigh[- ]risk\b|\bprocedure risk\s*[:=]\s*high\b|\brisk level\s*[:=]\s*high\b", risk_text):
        return "HIGH"
    return risk


def _excerpt(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
