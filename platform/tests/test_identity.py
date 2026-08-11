from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.identity.dependencies import require_role
from app.identity.oauth_client import TrueConfOAuthClient, client_from_env
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
    assert parsed.path == "/oauth/authorize"
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
    assert client.userinfo_path == "/api/v4/users/self"
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
