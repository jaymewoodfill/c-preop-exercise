"""Evidence and explanation builders for triage output."""

from __future__ import annotations

from typing import Any

from models import IssueCategory, TriageIssue, TriageIssueEvidence


def issue(category: IssueCategory, description: str, source: str, details: str) -> TriageIssue:
    return TriageIssue(
        category=category,
        description=description,
        evidence=TriageIssueEvidence(source=source, details=details),
    )


def explanation(issues: list[TriageIssue]) -> str:
    if not issues:
        return "All required criteria are satisfied."
    return " | ".join(f"{triage_issue.category}: {triage_issue.description}" for triage_issue in issues)


def document_summary(documents: list[dict[str, Any]], limit: int = 4) -> str:
    # Summaries ground missing-document issues without echoing unrelated patient
    # identifiers such as MRN/name into output.
    if not documents:
        return "none"
    parts = []
    for index, doc in enumerate(documents[:limit]):
        parts.append(f"documents[{index}] type={doc.get('type')!r} date={doc.get('date')!r}")
    return "; ".join(parts)


def lab_summary(labs: list[dict[str, Any]], limit: int = 4) -> str:
    if not labs:
        return "none"
    parts = []
    for index, lab in enumerate(labs[:limit]):
        parts.append(f"labs[{index}] code={lab.get('code')!r} effective_at={lab.get('effective_at')!r}")
    return "; ".join(parts)
