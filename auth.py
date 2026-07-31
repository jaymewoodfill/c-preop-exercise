"""Optional authentication/authorization boundary for service deployments.

The take-home harness calls ``triage_submission(...)`` directly, so auth is not part
of the core policy engine. This module demonstrates a small, dependency-free API
boundary: verify a signed bearer token, enforce tenant scope, then call the
triage engine.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from typing import Any

from core import PatientSubmission, TriageOutput, triage_submission


class AuthenticationError(ValueError):
    """Caller identity could not be established."""


class AuthorizationError(PermissionError):
    """Caller is authenticated but not allowed to access the submission."""


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str]
    expires_at: int


def sign_token(payload: dict[str, Any], secret: str | bytes) -> str:
    """Create a compact HMAC token for tests/dev demos.

    Production systems would usually use an identity provider and JWT/JWKS
    validation. HMAC keeps this take-home dependency-free while still showing the
    correct boundary and failure modes.
    """

    body = _b64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _signature(body, secret)
    return f"{body}.{signature}"


def authenticate_headers(headers: dict[str, str], secret: str | bytes, *, now: int | None = None) -> Principal:
    auth_header = _header_value(headers, "authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise AuthenticationError("Missing bearer token")

    token = auth_header.split(None, 1)[1].strip()
    payload = _verify_token(token, secret)
    current_time = int(time.time()) if now is None else now

    subject = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    expires_at = payload.get("exp")
    scopes = payload.get("scopes", [])

    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("Token missing subject")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise AuthenticationError("Token missing tenant_id")
    if not isinstance(expires_at, int):
        raise AuthenticationError("Token missing exp")
    if expires_at <= current_time:
        raise AuthenticationError("Token expired")
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise AuthenticationError("Token scopes must be a list of strings")

    return Principal(
        subject=subject,
        tenant_id=tenant_id,
        scopes=frozenset(scopes),
        expires_at=expires_at,
    )


def authorize_submission_access(
    principal: Principal,
    submission: dict[str, Any] | PatientSubmission,
    *,
    required_scope: str = "triage:evaluate",
) -> None:
    if required_scope not in principal.scopes:
        raise AuthorizationError(f"Missing required scope: {required_scope}")

    submission_payload = submission.model_dump() if isinstance(submission, PatientSubmission) else submission
    tenant_id = _submission_tenant_id(submission_payload)
    if tenant_id is None:
        raise AuthorizationError("Submission missing tenant_id/account_id metadata")
    if tenant_id != principal.tenant_id:
        raise AuthorizationError("Caller is not authorized for this tenant")


def triage_authenticated_submission(
    submission: dict[str, Any] | PatientSubmission,
    *,
    headers: dict[str, str],
    secret: str | bytes,
    model: str,
) -> TriageOutput:
    """Authenticate caller, authorize tenant access, then evaluate submission."""

    principal = authenticate_headers(headers, secret)
    authorize_submission_access(principal, submission)
    return triage_submission(submission, model=model)


def _verify_token(token: str, secret: str | bytes) -> dict[str, Any]:
    try:
        body, provided_signature = token.split(".", 1)
    except ValueError as exc:
        raise AuthenticationError("Malformed bearer token") from exc

    expected_signature = _signature(body, secret)
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise AuthenticationError("Invalid token signature")

    try:
        payload = json.loads(_b64url_decode(body))
    except (json.JSONDecodeError, ValueError) as exc:
        raise AuthenticationError("Invalid token payload") from exc
    if not isinstance(payload, dict):
        raise AuthenticationError("Token payload must be an object")
    return payload


def _signature(body: str, secret: str | bytes) -> str:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    digest = hmac.new(key, body.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8")


def _header_value(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _submission_tenant_id(submission: dict[str, Any]) -> str | None:
    metadata = submission.get("metadata")
    if not isinstance(metadata, dict):
        return None
    tenant_id = metadata.get("tenant_id") or metadata.get("account_id")
    return tenant_id if isinstance(tenant_id, str) and tenant_id else None
