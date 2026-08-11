"""Pure logic tests for the cross-origin login allowlist
(app/identity/return_to.py) -- no FastAPI, no OAuth, no database.
"""
from app.identity.return_to import parse_allowlist, validate_return_to


def test_parse_allowlist_splits_on_comma_and_strips_whitespace():
    allowlist = parse_allowlist(" http://a:1 , http://b:2 ")

    assert allowlist == frozenset({"http://a:1", "http://b:2"})


def test_parse_allowlist_strips_trailing_slash():
    allowlist = parse_allowlist("http://a:1/")

    assert allowlist == frozenset({"http://a:1"})


def test_parse_allowlist_of_empty_string_is_empty():
    assert parse_allowlist("") == frozenset()


def test_validate_return_to_accepts_an_allowlisted_origin():
    allowlist = frozenset({"http://localhost:8091"})

    assert validate_return_to("http://localhost:8091", allowlist) == "http://localhost:8091"


def test_validate_return_to_strips_a_path_down_to_the_origin():
    allowlist = frozenset({"http://localhost:8091"})

    assert validate_return_to("http://localhost:8091/some/path?x=1", allowlist) == "http://localhost:8091"


def test_validate_return_to_rejects_an_origin_not_on_the_allowlist():
    allowlist = frozenset({"http://localhost:8091"})

    assert validate_return_to("http://evil.example:1337", allowlist) is None


def test_validate_return_to_rejects_none():
    assert validate_return_to(None, frozenset({"http://localhost:8091"})) is None


def test_validate_return_to_rejects_empty_string():
    assert validate_return_to("", frozenset({"http://localhost:8091"})) is None


def test_validate_return_to_rejects_a_bare_path_with_no_origin():
    assert validate_return_to("/just/a/path", frozenset({"http://localhost:8091"})) is None


def test_validate_return_to_is_scheme_sensitive():
    """http://x and https://x are different origins -- allowlisting one
    must not silently accept the other.
    """
    allowlist = frozenset({"https://localhost:8091"})

    assert validate_return_to("http://localhost:8091", allowlist) is None


def test_validate_return_to_is_port_sensitive():
    allowlist = frozenset({"http://localhost:8091"})

    assert validate_return_to("http://localhost:9999", allowlist) is None


def test_validate_return_to_against_empty_allowlist_rejects_everything():
    assert validate_return_to("http://localhost:8091", frozenset()) is None
