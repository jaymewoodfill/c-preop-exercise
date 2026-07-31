from __future__ import annotations

import pytest

from auth import (
    AuthenticationError,
    AuthorizationError,
    authenticate_headers,
    authorize_submission_access,
    sign_token,
    triage_authenticated_submission,
)


SECRET = "test-secret"
NOW = 1_800_000_000


def tenant_submission(tenant_id: str = "tenant-a") -> dict[str, object]:
    return {
        "patient": {"id": "patient-1"},
        "procedure": {
            "case_id": "case-1",
            "procedure_risk": "LOW",
            "procedure_date": "2026-02-01",
        },
        "vitals": [
            {"type": "blood_pressure", "systolic": 120, "diastolic": 80, "date": "2026-01-25T09:00:00Z"},
            {"type": "temperature", "value_f": 98.6, "date": "2026-01-25T09:05:00Z"},
        ],
        "labs": [
            {"code": "CBC", "display": "Complete Blood Count", "effective_at": "2026-01-20T08:00:00Z", "status": "final"},
        ],
        "medications": [],
        "conditions": [],
        "documents": [
            {"type": "History and Physical", "date": "2026-01-20", "text": "H&P note complete."},
            {"type": "Surgical Consent", "date": "2026-01-22", "text": "Signed surgical consent."},
        ],
        "metadata": {"tenant_id": tenant_id, "submission_received_at": "2026-01-26T12:00:00Z"},
    }


def bearer(payload: dict[str, object]) -> dict[str, str]:
    return {"Authorization": "Bearer " + sign_token(payload, SECRET)}


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "scopes": ["triage:evaluate"],
        "exp": NOW + 60,
    }
    payload.update(overrides)
    return payload


def test_valid_bearer_token_can_evaluate_authorized_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("auth.time.time", lambda: NOW)

    output = triage_authenticated_submission(
        tenant_submission("tenant-a"),
        headers=bearer(valid_payload()),
        secret=SECRET,
        model="ignored-model",
    )

    assert output.decision == "READY"


def test_missing_bearer_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        authenticate_headers({}, SECRET, now=NOW)


def test_tampered_token_is_rejected() -> None:
    token = sign_token(valid_payload(), SECRET)
    body, signature = token.split(".", 1)
    tampered_body = ("A" if body[0] != "A" else "B") + body[1:]
    tampered = f"{tampered_body}.{signature}"

    with pytest.raises(AuthenticationError):
        authenticate_headers({"Authorization": f"Bearer {tampered}"}, SECRET, now=NOW)


def test_expired_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        authenticate_headers(bearer(valid_payload(exp=NOW - 1)), SECRET, now=NOW)


def test_missing_scope_is_rejected() -> None:
    principal = authenticate_headers(bearer(valid_payload(scopes=["triage:read"])), SECRET, now=NOW)

    with pytest.raises(AuthorizationError):
        authorize_submission_access(principal, tenant_submission("tenant-a"))


def test_cross_tenant_submission_is_rejected() -> None:
    principal = authenticate_headers(bearer(valid_payload(tenant_id="tenant-a")), SECRET, now=NOW)

    with pytest.raises(AuthorizationError):
        authorize_submission_access(principal, tenant_submission("tenant-b"))


def test_submission_without_tenant_metadata_is_rejected() -> None:
    principal = authenticate_headers(bearer(valid_payload()), SECRET, now=NOW)
    submission = tenant_submission("tenant-a")
    submission["metadata"] = {}

    with pytest.raises(AuthorizationError):
        authorize_submission_access(principal, submission)


def test_client_supplied_patient_id_does_not_grant_cross_tenant_access() -> None:
    principal = authenticate_headers(bearer(valid_payload(tenant_id="tenant-a")), SECRET, now=NOW)
    submission = tenant_submission("tenant-b")
    submission["patient"] = {"id": "tenant-a-looking-patient-id"}

    with pytest.raises(AuthorizationError):
        authorize_submission_access(principal, submission)
