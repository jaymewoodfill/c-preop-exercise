"""Deterministic Cadence pre-op triage policy rules."""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any

from evidence import document_summary, explanation, issue, lab_summary
from models import Decision, PatientSubmission, TriageIssue, TriageOutput
from parsing import (
    as_dict,
    as_list,
    excerpt,
    format_number,
    normalized_text,
    number,
    parse_date,
    parse_datetime,
)

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
POSTOP_PLAN_TERMS = (
    "resume",
    "restart",
    "re-start",
    "post-op",
    "postoperative",
    "post-operative",
    "after surgery",
)

HIGH_RISK_NEGATION_RE = re.compile(
    r"\b(?:not|no|non|never|without|denies|denied|ruled out)\s+(?:a\s+)?high[- ]risk\b"
)
HIGH_RISK_RE = re.compile(
    r"\bhigh[- ]risk\b|\bprocedure risk\s*[:=]\s*high\b|\brisk level\s*[:=]\s*high\b"
)


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
    procedure = as_dict(payload.get("procedure"))
    procedure_date_raw = procedure.get("procedure_date")
    procedure_date = parse_date(procedure_date_raw)
    procedure_risk = procedure.get("procedure_risk")
    metadata = as_dict(payload.get("metadata"))
    review_datetime = _review_datetime(metadata, procedure_date_raw)

    # Structured procedure date is treated as authoritative; document text may
    # mention target dates, but inferring from free text would hide missing data.
    if procedure_date_raw in (None, ""):
        issues.append(
            issue(
                "MISSING_REQUIRED_DATA",
                "Missing procedure date",
                "procedure.procedure_date",
                "procedure.procedure_date is null",
            )
        )
    elif procedure_date is None:
        issues.append(
            issue(
                "MISSING_REQUIRED_DATA",
                "Invalid procedure date",
                "procedure.procedure_date",
                f"procedure.procedure_date={procedure_date_raw!r} is not a valid date",
            )
        )

    if procedure_risk is None:
        issues.append(
            issue(
                "MISSING_REQUIRED_DATA",
                "Missing procedure risk",
                "procedure.procedure_risk",
                "procedure.procedure_risk is null",
            )
        )

    documents = as_list(payload.get("documents"))
    labs = as_list(payload.get("labs"))
    vitals = as_list(payload.get("vitals"))
    medications = as_list(payload.get("medications"))
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
            issue(
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
    if any(triage_issue.category == "ACUTE_SAFETY_EXCLUSION" for triage_issue in issues):
        decision: Decision = "NOT_CLEARED"
    elif issues:
        decision = "NEEDS_FOLLOW_UP"
    else:
        decision = "READY"

    return TriageOutput(decision=decision, issues=issues, explanation=explanation(issues))


def _review_datetime(metadata: dict[str, Any], procedure_date_raw: Any) -> datetime | None:
    submitted_at = parse_datetime(metadata.get("submission_received_at"))
    if submitted_at is not None:
        return submitted_at
    procedure_date = parse_date(procedure_date_raw)
    if procedure_date is None:
        return None
    return datetime.combine(procedure_date, time.max)


def _documentation_presence_issues(documents: list[dict[str, Any]]) -> list[TriageIssue]:
    # Used when procedure_date is missing: report missing docs, but avoid
    # pretending we can evaluate 30-day freshness without the anchor date.
    issues: list[TriageIssue] = []
    hp_docs = [(doc, i, parse_date(doc.get("date"))) for i, doc in enumerate(documents) if _is_hp_document(doc)]
    consent_docs = [(doc, i) for i, doc in enumerate(documents) if _is_consent_document(doc)]
    if not any(doc_date is not None for _, _, doc_date in hp_docs):
        issues.append(
            issue(
                "REQUIRED_DOCUMENTATION",
                "History and Physical document missing",
                "documents",
                f"No History and Physical document with valid date found; documents include: {document_summary(documents)}",
            )
        )
    if not consent_docs:
        issues.append(
            issue(
                "REQUIRED_DOCUMENTATION",
                "Signed surgical consent missing",
                "documents",
                f"No Surgical Consent document found; documents include: {document_summary(documents)}",
            )
        )
    else:
        unsigned = _first_unsigned_consent(consent_docs)
        if unsigned is not None:
            doc, index = unsigned
            issues.append(
                issue(
                    "REQUIRED_DOCUMENTATION",
                    "Surgical consent not clearly signed",
                    f"documents[{index}]",
                    f"Consent document text does not clearly indicate signed consent: {excerpt(doc.get('text'))}",
                )
            )
    return issues


def _documentation_issues(documents: list[dict[str, Any]], procedure_date) -> list[TriageIssue]:
    issues: list[TriageIssue] = []
    hp_docs = [(doc, i, parse_date(doc.get("date"))) for i, doc in enumerate(documents) if _is_hp_document(doc)]
    valid_hp_docs = [(doc, i, doc_date) for doc, i, doc_date in hp_docs if doc_date is not None]
    if not valid_hp_docs:
        issues.append(
            issue(
                "REQUIRED_DOCUMENTATION",
                "History and Physical document missing",
                "documents",
                f"No History and Physical document with valid date found; documents include: {document_summary(documents)}",
            )
        )
    else:
        doc, index, doc_date = max(valid_hp_docs, key=lambda item: (item[2], -item[1]))
        days_prior = (procedure_date - doc_date).days
        if days_prior < 0 or days_prior > 30:
            issues.append(
                issue(
                    "REQUIRED_DOCUMENTATION",
                    "H&P outside 30-day window",
                    f"documents[{index}]",
                    f"H&P date {doc_date.isoformat()} vs procedure_date {procedure_date.isoformat()} ({days_prior} days prior; must be within 30)",
                )
            )

    consent_docs = [(doc, i) for i, doc in enumerate(documents) if _is_consent_document(doc)]
    if not consent_docs:
        issues.append(
            issue(
                "REQUIRED_DOCUMENTATION",
                "Signed surgical consent missing",
                "documents",
                f"No Surgical Consent document found; documents include: {document_summary(documents)}",
            )
        )
    else:
        unsigned = _first_unsigned_consent(consent_docs)
        if unsigned is not None:
            doc, index = unsigned
            issues.append(
                issue(
                    "REQUIRED_DOCUMENTATION",
                    "Surgical consent not clearly signed",
                    f"documents[{index}]",
                    f"Consent document text does not clearly indicate signed consent: {excerpt(doc.get('text'))}",
                )
            )
    return issues


def _testing_issues(labs: list[dict[str, Any]], procedure_date, procedure_risk: str) -> list[TriageIssue]:
    issues: list[TriageIssue] = []
    requirements = [("CBC", 30)] if procedure_risk in {"LOW", "MODERATE"} else [("CBC", 14), ("CMP", 14)]
    for lab_code, max_days in requirements:
        matching = [(lab, i, parse_date(lab.get("effective_at"))) for i, lab in enumerate(labs) if _is_lab(lab, lab_code)]
        valid = [(lab, i, lab_date) for lab, i, lab_date in matching if lab_date is not None]
        if not valid:
            issues.append(
                issue(
                    "REQUIRED_TESTING",
                    f"{lab_code} missing",
                    "labs",
                    f"No {lab_code} result with valid effective_at found for procedure_risk {procedure_risk}; labs include: {lab_summary(labs)}",
                )
            )
            continue
        # Policy says only the most recent result for each required test counts.
        lab, index, lab_date = max(valid, key=lambda item: (item[2], -item[1]))
        days_prior = (procedure_date - lab_date).days
        if days_prior < 0 or days_prior > max_days:
            issues.append(
                issue(
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
        text = normalized_text(_document_text(doc))
        mentions_med = any(name and name in text for name in med_names)
        mentions_anticoag = "anticoag" in text or "blood thinner" in text
        mentions_plan = any(
            term in text
            for term in (
                "periop",
                "peri-op",
                "perioperative",
                "procedure",
                "surgery",
                "anticoag plan",
                "medication plan",
                "blood thinner",
            )
        )
        if (mentions_med or mentions_anticoag) and mentions_plan:
            best_source = f"documents[{index}]"
            best_excerpt = excerpt(doc.get("text"))
            if _is_clear_anticoagulation_plan(text):
                return None
    details = f"Active anticoagulant medication present ({med_refs}) but no clear perioperative plan document found"
    if best_source != "documents":
        details = f"{details}; document excerpt: {best_excerpt}"
    return issue("ANTICOAGULATION_MANAGEMENT", "Missing perioperative anticoagulation plan", best_source, details)


def _vital_issues(vitals: list[dict[str, Any]], review_datetime: datetime | None) -> list[TriageIssue]:
    issues: list[TriageIssue] = []
    latest_bp = _latest_vital(vitals, "blood_pressure", review_datetime)
    latest_temp = _latest_vital(vitals, "temperature", review_datetime)

    if latest_bp is None:
        issues.append(issue("MISSING_REQUIRED_DATA", "Missing latest blood pressure", "vitals", "No blood_pressure vital with valid date found"))
    else:
        vital, index = latest_bp
        systolic = vital.get("systolic")
        diastolic = vital.get("diastolic")
        if number(systolic) is None or number(diastolic) is None:
            issues.append(
                issue(
                    "MISSING_REQUIRED_DATA",
                    "Missing latest blood pressure",
                    f"vitals[{index}]",
                    f"latest BP systolic={systolic}, diastolic={diastolic}; both values are required",
                )
            )
        elif number(systolic) >= 180 or number(diastolic) >= 110:
            issues.append(
                issue(
                    "ACUTE_SAFETY_EXCLUSION",
                    "Blood pressure meets exclusion threshold",
                    f"vitals[{index}]",
                    f"latest BP systolic={format_number(systolic)}, diastolic={format_number(diastolic)} on {vital.get('date')}; threshold systolic>=180 or diastolic>=110",
                )
            )

    if latest_temp is None:
        issues.append(issue("MISSING_REQUIRED_DATA", "Missing latest temperature", "vitals", "No temperature vital with valid date found"))
    else:
        vital, index = latest_temp
        value_f = vital.get("value_f")
        if number(value_f) is None:
            issues.append(
                issue(
                    "MISSING_REQUIRED_DATA",
                    "Missing latest temperature",
                    f"vitals[{index}]",
                    f"latest temperature value_f={value_f}; value_f is required",
                )
            )
        elif number(value_f) > 100.4:
            issues.append(
                issue(
                    "ACUTE_SAFETY_EXCLUSION",
                    "Temperature exceeds exclusion threshold",
                    f"vitals[{index}]",
                    f"latest temperature value_f={format_number(value_f)} on {vital.get('date')}; threshold is > 100.4",
                )
            )

    return issues


def _document_text(doc: dict[str, Any]) -> str:
    return "\n".join(str(part) for part in (doc.get("type"), doc.get("text"), doc.get("author")) if part)


def _is_hp_document(doc: dict[str, Any]) -> bool:
    doc_type = normalized_text(doc.get("type"))
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
    doc_type = normalized_text(doc.get("type"))
    text = normalized_text(doc.get("text"))
    if "not a consent" in text:
        # Prevent false positives from adversarial or clarifying note text.
        return False
    # Require a consent-like document type; arbitrary notes with "signed consent"
    # in the body are treated as evidence at most, not as the required document.
    return "consent" in doc_type


def _first_unsigned_consent(consent_docs: list[tuple[dict[str, Any], int]]) -> tuple[dict[str, Any], int] | None:
    for doc, index in consent_docs:
        text = normalized_text(_document_text(doc))
        if "unsigned" in text or "awaiting patient signature" in text or "signature not yet" in text:
            return doc, index
        if "signed" not in text and "signature" not in text:
            return doc, index
    return None


def _is_lab(lab: dict[str, Any], code: str) -> bool:
    status = normalized_text(lab.get("status"))
    if status and status not in {"final", "corrected", "amended"}:
        return False

    lab_code = str(lab.get("code") or "").upper().strip()
    display = normalized_text(lab.get("display"))
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
    normalized = normalized_text(text)
    if any(term in normalized for term in AMBIGUOUS_PLAN_TERMS):
        return False
    # Require both pre-op and post-op management language; a partial plan is not
    # enough to satisfy the policy requirement for clear perioperative management.
    return any(term in normalized for term in PREOP_PLAN_TERMS) and any(term in normalized for term in POSTOP_PLAN_TERMS)


def _latest_vital(vitals: list[dict[str, Any]], vital_type: str, review_datetime: datetime | None) -> tuple[dict[str, Any], int] | None:
    # Acute safety rules use only the latest relevant vital. Future-dated rows and
    # non-finite values cannot safely establish current review state.
    valid: list[tuple[dict[str, Any], int, datetime]] = []
    for index, vital in enumerate(vitals):
        if str(vital.get("type") or "").lower() != vital_type:
            continue
        vital_date = parse_datetime(vital.get("date"))
        if vital_date is None:
            continue
        if review_datetime is not None and vital_date > review_datetime:
            continue
        if vital_type == "blood_pressure" and (number(vital.get("systolic")) is None or number(vital.get("diastolic")) is None):
            continue
        if vital_type == "temperature" and number(vital.get("value_f")) is None:
            continue
        valid.append((vital, index, vital_date))
    if not valid:
        return None
    vital, index, _ = max(valid, key=lambda item: (item[2], -item[1]))
    return vital, index


def _effective_procedure_risk(procedure_risk: str | None, procedure: dict[str, Any], documents: list[dict[str, Any]]) -> str | None:
    risk_text = " ".join(
        [_risk_text_source(normalized_text(procedure.get("procedure_type")))]
        + [_risk_text_source(normalized_text(doc.get("type")) + " " + normalized_text(doc.get("text"))) for doc in documents]
    )
    # If any submitted materials describe the case as high risk, conservatively
    # apply the stricter HIGH testing gate even if the structured field is lower.
    # Avoid obvious negated phrases such as "not high-risk" to reduce false positives.
    if HIGH_RISK_RE.search(risk_text):
        return "HIGH"
    return procedure_risk


def _risk_text_source(text: str) -> str:
    return HIGH_RISK_NEGATION_RE.sub(" ", text)
