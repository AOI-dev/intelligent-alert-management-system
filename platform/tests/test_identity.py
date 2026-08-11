from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.identity.router as router
from app.identity.dependencies import require_role
from app.identity.models import Identity
import app.identity.repository as repository
from app.identity.oauth_client import TrueConfOAuthClient, _dig, client_from_env
from app.identity.session import issue_session_cookie, read_session_cookie


def _client() -> TrueConfOAuthClient:
    return TrueConfOAuthClient(
        base_url="https://trueconf.internal",
        client_id="the-client-id",
        client_secret="the-secret",
        redirect_uri="http://localhost:8100/v1/auth/callback",
    )


def test_authorize_url_carries_required_params():
    url = _client().authorize_url(state="opaque-state")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "trueconf.internal"
    assert parsed.path == "/oauth2/authorize"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["the-client-id"]
    assert query["redirect_uri"] == ["http://localhost:8100/v1/auth/callback"]
    assert query["state"] == ["opaque-state"]


def test_client_from_env_reads_all_required_vars(monkeypatch):
    monkeypatch.setenv("TRUECONF_BASE_URL", "https://trueconf.internal")
    monkeypatch.setenv("TRUECONF_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TRUECONF_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TRUECONF_OAUTH_REDIRECT_URI", "http://localhost/cb")

    client = client_from_env()

    assert client.base_url == "https://trueconf.internal"
    assert client.client_id == "cid"
    assert client.verify_ssl is True  # secure by default


def test_client_from_env_verify_ssl_false_only_when_explicitly_set(monkeypatch):
    monkeypatch.setenv("TRUECONF_BASE_URL", "https://trueconf.internal")
    monkeypatch.setenv("TRUECONF_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TRUECONF_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TRUECONF_OAUTH_REDIRECT_URI", "http://localhost/cb")
    monkeypatch.setenv("TRUECONF_VERIFY_SSL", "false")

    assert client_from_env().verify_ssl is False


def test_client_from_env_missing_var_raises(monkeypatch):
    for key in ["TRUECONF_BASE_URL", "TRUECONF_OAUTH_CLIENT_ID", "TRUECONF_OAUTH_CLIENT_SECRET", "TRUECONF_OAUTH_REDIRECT_URI"]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(KeyError):
        client_from_env()


def test_session_cookie_roundtrip():
    identity_id = uuid4()
    cookie = issue_session_cookie(identity_id)

    assert read_session_cookie(cookie) == identity_id


def test_session_cookie_rejects_tampered_value():
    cookie = issue_session_cookie(uuid4())
    tampered = cookie[:-1] + ("a" if cookie[-1] != "a" else "b")

    assert read_session_cookie(tampered) is None


def test_session_cookie_rejects_garbage():
    assert read_session_cookie("not-a-real-cookie") is None


def _identity_with_roles(*role_ids: str) -> SimpleNamespace:
    return SimpleNamespace(roles=[SimpleNamespace(role_id=role_id) for role_id in role_ids])


@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    dependency = require_role("admin")
    identity = _identity_with_roles("viewer", "admin")

    result = await dependency(identity=identity)

    assert result is identity


@pytest.mark.asyncio
async def test_require_role_rejects_missing_role():
    dependency = require_role("admin")
    identity = _identity_with_roles("viewer")

    with pytest.raises(HTTPException) as excinfo:
        await dependency(identity=identity)

    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_rejects_no_roles():
    dependency = require_role("admin", "engineer")
    identity = _identity_with_roles()

    with pytest.raises(HTTPException) as excinfo:
        await dependency(identity=identity)

    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_callback_falls_back_to_the_state_cookie():
    """TrueConf Server 5.5 hands the callback a bare `?code=...` with no
    `state` (confirmed against the deployed server), so the signed state
    the login step also stashed in a cookie is what has to carry
    `return_to` and the CSRF nonce through.
    """
    state = router._state_serializer.dumps({"nonce": "n", "return_to": None})
    exchanged = {}

    class _StubClient:
        async def exchange_code(self, code):
            exchanged["code"] = code
            return "access-token"

        async def fetch_profile(self, _token):
            return SimpleNamespace(subject="tc-subject", display_label="TC User")

    async def _provision(_session, subject, label):
        return Identity(id=uuid4(), trueconf_subject=subject, display_label=label)

    with (
        mock.patch.object(router, "_oauth_client", lambda: _StubClient()),
        mock.patch.object(router, "get_or_provision_identity", _provision),
    ):
        response = await router.callback(code="the-code", state=None, tc_oauth_state=state, session=None)

    assert exchanged["code"] == "the-code"
    assert response.status_code in (302, 307)


@pytest.mark.asyncio
async def test_callback_rejects_a_missing_state_everywhere():
    with pytest.raises(HTTPException) as excinfo:
        await router.callback(code="the-code", state=None, tc_oauth_state=None, session=None)

    assert excinfo.value.status_code == 400


def test_dig_reads_the_nested_me_payload():
    """TrueConf 5.5's /api/v4/me nests the profile under "user" -- the
    claim settings are dotted paths for exactly that reason.
    """
    payload = {"user": {"id": "oleg_ai@tc", "display_name": "Oleg"}, "admin": False}

    assert _dig(payload, "user.id") == "oleg_ai@tc"
    assert _dig(payload, "user.display_name") == "Oleg"
    assert _dig(payload, "admin") is False


def test_dig_returns_none_for_paths_that_are_not_there():
    assert _dig({"user": {"id": 1}}, "user.display_name") is None
    assert _dig({"user": {"id": 1}}, "nope.id") is None
    # A non-dict partway down is a miss, not a TypeError.
    assert _dig({"user": "not-a-dict"}, "user.id") is None


def test_client_from_env_defaults_to_the_endpoint_a_user_token_can_read(monkeypatch):
    """/api/v4/users/self is admin-only and 403s for a user's own OAuth
    token -- the default has to be the endpoint that actually works.
    """
    for name, value in {
        "TRUECONF_BASE_URL": "https://trueconf.internal",
        "TRUECONF_OAUTH_CLIENT_ID": "cid",
        "TRUECONF_OAUTH_CLIENT_SECRET": "secret",
        "TRUECONF_OAUTH_REDIRECT_URI": "https://trueconf.internal/v1/auth/callback",
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("TRUECONF_USERINFO_PATH", "TRUECONF_USERINFO_SUBJECT_FIELD", "TRUECONF_USERINFO_DISPLAY_FIELD"):
        monkeypatch.delenv(name, raising=False)

    client = client_from_env()

    assert client.userinfo_path == "/api/v4/me"
    assert client.subject_field == "user.id"
    assert client.display_field == "user.display_name"


def test_bootstrap_admin_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("AUTH_BOOTSTRAP_FIRST_ADMIN", raising=False)
    assert repository._bootstrap_admin_enabled() is False

    monkeypatch.setenv("AUTH_BOOTSTRAP_FIRST_ADMIN", "true")
    assert repository._bootstrap_admin_enabled() is True

    monkeypatch.setenv("AUTH_BOOTSTRAP_FIRST_ADMIN", "false")
    assert repository._bootstrap_admin_enabled() is False
