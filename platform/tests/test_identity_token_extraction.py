"""_token_from_request (app/identity/dependencies.py): the same signed
token works as either a same-host cookie or a cross-origin Authorization
header. Built against minimal ASGI scopes rather than a real HTTP
request/TestClient -- see tests/test_main_routes.py's docstring for why
this repo avoids TestClient(app) for platform (it triggers a real
Kafka-connecting lifespan that hangs with no broker reachable).
"""
from fastapi import Request

from app.identity.dependencies import _token_from_request
from app.identity.session import SESSION_COOKIE_NAME


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "headers": headers or [],
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


def test_reads_the_token_from_the_session_cookie():
    request = _request(headers=[(b"cookie", f"{SESSION_COOKIE_NAME}=abc123".encode())])

    assert _token_from_request(request) == "abc123"


def test_reads_the_token_from_a_bearer_authorization_header():
    request = _request(headers=[(b"authorization", b"Bearer abc123")])

    assert _token_from_request(request) == "abc123"


def test_bearer_header_is_case_insensitive():
    request = _request(headers=[(b"authorization", b"bearer abc123")])

    assert _token_from_request(request) == "abc123"


def test_cookie_takes_precedence_over_header_when_both_present():
    request = _request(
        headers=[
            (b"cookie", f"{SESSION_COOKIE_NAME}=from-cookie".encode()),
            (b"authorization", b"Bearer from-header"),
        ]
    )

    assert _token_from_request(request) == "from-cookie"


def test_returns_none_when_neither_is_present():
    request = _request()

    assert _token_from_request(request) is None


def test_ignores_a_non_bearer_authorization_header():
    request = _request(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])

    assert _token_from_request(request) is None
