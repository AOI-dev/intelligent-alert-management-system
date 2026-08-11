"""Signed session cookie carrying only an identity id — no secrets, no
roles (roles are re-read from the DB on every request so revocation is
immediate rather than waiting out a stale token).
"""
import os
from uuid import UUID

from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "platform_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60

_serializer = URLSafeTimedSerializer(os.environ.get("SESSION_SECRET_KEY", "dev-insecure-change-me"))


def issue_session_cookie(identity_id: UUID) -> str:
    return _serializer.dumps({"identity_id": str(identity_id)})


def read_session_cookie(value: str) -> UUID | None:
    try:
        payload = _serializer.loads(value, max_age=SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None
    try:
        return UUID(payload["identity_id"])
    except (KeyError, ValueError):
        return None
