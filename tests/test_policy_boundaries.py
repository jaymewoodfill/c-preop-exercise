from __future__ import annotations

from core import triage_submission


def base_submission() -> dict[str, object]:
    return {
        "patient": {"id": "patient-1"},
        "procedure": {
            "case_id": "case-1",
            "procedure_risk": "MODERATE",
            "procedure_date": "2026-03-01",
        },
        "vitals": [
            {
                "type": "blood_pressure",
                "systolic": 120,
                "diastolic": 80,
                "date": "2026-02-25T09:00:00Z",
            },
            {
                "type": "temperature",
                "value_f": 98.6,
                "date": "2026-02-25T09:05:00Z",
            },
        ],
        "labs": [
            {
                "code": "CBC",
                "display": "Complete Blood Count",
                "effective_at": "2026-02-20T08:00:00Z",
                "status": "final",
            }
        ],
        "medications": [],
        "conditions": [],
        "documents": [
            {
                "type": "History and Physical",
                "date": "2026-02-20",
                "text": "H&P note: assessment and plan documented.",
            },
            {
                "type": "Surgical Consent",
                "date": "2026-02-21",
                "text": "Signed surgical consent.",
            },
        ],
    }


def categories(output) -> list[str]:
    return [issue.category for issue in output.issues]


def test_hp_exactly_30_days_prior_is_current() -> None:
    payload = base_submission()
    payload["documents"][0]["date"] = "2026-01-30"  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "READY"


def test_hp_31_days_prior_is_outdated() -> None:
    payload = base_submission()
    payload["documents"][0]["date"] = "2026-01-29"  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "NEEDS_FOLLOW_UP"
    assert "REQUIRED_DOCUMENTATION" in categories(output)


def test_moderate_cbc_exactly_30_days_prior_is_current() -> None:
    payload = base_submission()
    payload["labs"][0]["effective_at"] = "2026-01-30T08:00:00Z"  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "READY"


def test_moderate_cbc_31_days_prior_is_outdated() -> None:
    payload = base_submission()
    payload["labs"][0]["effective_at"] = "2026-01-29T08:00:00Z"  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "NEEDS_FOLLOW_UP"
    assert "REQUIRED_TESTING" in categories(output)


def test_high_risk_labs_exactly_14_days_prior_are_current() -> None:
    payload = base_submission()
    payload["procedure"]["procedure_risk"] = "HIGH"  # type: ignore[index]
    payload["labs"] = [
        {
            "code": "CBC",
            "display": "Complete Blood Count",
            "effective_at": "2026-02-15T08:00:00Z",
            "status": "final",
        },
        {
            "code": "CMP",
            "display": "Comprehensive Metabolic Panel",
            "effective_at": "2026-02-15T08:00:00Z",
            "status": "final",
        },
    ]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "READY"


def test_high_risk_lab_15_days_prior_is_outdated() -> None:
    payload = base_submission()
    payload["procedure"]["procedure_risk"] = "HIGH"  # type: ignore[index]
    payload["labs"] = [
        {
            "code": "CBC",
            "display": "Complete Blood Count",
            "effective_at": "2026-02-14T08:00:00Z",
            "status": "final",
        },
        {
            "code": "CMP",
            "display": "Comprehensive Metabolic Panel",
            "effective_at": "2026-02-15T08:00:00Z",
            "status": "final",
        },
    ]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "NEEDS_FOLLOW_UP"
    assert "REQUIRED_TESTING" in categories(output)


def test_temperature_exactly_100_4_is_not_exclusion() -> None:
    payload = base_submission()
    payload["vitals"][1]["value_f"] = 100.4  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "READY"


def test_temperature_above_100_4_is_exclusion() -> None:
    payload = base_submission()
    payload["vitals"][1]["value_f"] = 100.5  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "NOT_CLEARED"
    assert "ACUTE_SAFETY_EXCLUSION" in categories(output)


def test_systolic_180_is_exclusion() -> None:
    payload = base_submission()
    payload["vitals"][0]["systolic"] = 180  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "NOT_CLEARED"
    assert "ACUTE_SAFETY_EXCLUSION" in categories(output)


def test_diastolic_110_is_exclusion() -> None:
    payload = base_submission()
    payload["vitals"][0]["diastolic"] = 110  # type: ignore[index]

    output = triage_submission(payload, model="ignored-model")

    assert output.decision == "NOT_CLEARED"
    assert "ACUTE_SAFETY_EXCLUSION" in categories(output)
