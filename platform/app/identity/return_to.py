"""Validates the `return_to` origin a cross-origin login flow redirects
back to (see app/identity/router.py's login/callback).

Kept separate and pure so the allowlist logic is testable without FastAPI,
OAuth, or a database. This exists because TrueConf's OAuth2 redirect_uri
is fixed to one host (a real constraint of OAuth2 itself, not something
we chose) -- so a session cookie set during that callback is only ever
valid for that host. A frontend running anywhere else (a dev's own
machine, a second deployment) needs the identity this process already
established to be handed to it directly, as a portable bearer token
delivered via URL fragment, not inferred from a cookie it will never see.

Without validation, `return_to` would be an open redirect that also leaks
a live session token to wherever an attacker points it (the token rides
in the fragment of the URL we redirect to) -- so it's only ever honored
when it exactly matches a configured origin, never accepted as free text.
"""

from urllib.parse import urlparse


def parse_allowlist(raw: str) -> frozenset[str]:
    """Env var value ("http://a:1,http://b:2") -> a set of origins."""
    return frozenset(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())


def validate_return_to(return_to: str | None, allowlist: frozenset[str]) -> str | None:
    """Returns `return_to`'s origin (scheme://host[:port], no path) if it
    exactly matches an allowlisted origin, else None. A None input, an
    unparseable value, or a non-match are all treated the same way:
    silently ignored, falling back to the default same-host cookie flow --
    this is a "nice to have" allowance, never a required parameter, so
    failing closed here is the right default rather than erroring the
    whole login attempt.
    """
    if not return_to:
        return None
    try:
        parsed = urlparse(return_to)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin if origin in allowlist else None
