"""TrueConf Server OAuth 2.0 client (Authorization Code flow), per
https://trueconf.com/docs/server/en/admin/api/ — create the OAuth2
application under the server's control panel at API -> OAuth2 first; it
hands out the client_id/client_secret this client is configured with.

Exact userinfo endpoint/claim names aren't published outside the
server's own /api/v4/docs/ (version-specific), so both the path and the
claim keys pulled from the response are env-configurable rather than
hardcoded — set them from the deployed server's live API docs.
"""
import os
from dataclasses import dataclass

import httpx


def _dig(payload: dict, dotted_field: str):
    """Look a dotted path up in a decoded JSON body, e.g. `user.id`.

    The claim names were always env-configurable (see the module
    docstring); nesting is why they now have to be *paths* rather than
    plain keys. TrueConf 5.5's /api/v4/me answers
    `{"user": {"id": …, "display_name": …}, "admin": …, "guest": …}`,
    so the interesting values are one level down.
    """
    current = payload
    for part in dotted_field.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


@dataclass(frozen=True)
class TrueConfProfile:
    subject: str
    display_label: str


class TrueConfOAuthClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        userinfo_path: str = "/api/v4/me",
        subject_field: str = "user.id",
        display_field: str = "user.display_name",
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.userinfo_path = userinfo_path
        self.subject_field = subject_field
        self.display_field = display_field
        # False only for the self-signed cert trueconf-tls/ uses (no
        # domain name for this VM means no publicly-trusted cert is
        # possible -- see that stack's README). The browser accepts a
        # self-signed cert with a one-time click-through warning; httpx
        # here has no such prompt, so it needs telling explicitly not to
        # reject it. Never set this False against a real, publicly-trusted
        # TrueConf deployment.
        self.verify_ssl = verify_ssl

    def authorize_url(self, state: str) -> str:
        params = httpx.QueryParams(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        # TrueConf Server 5.5 serves its OAuth UI under /oauth2/authorize.
        # The older /oauth/authorize path returns 404 on the deployed server.
        return f"{self.base_url}/oauth2/authorize?{params}"

    async def exchange_code(self, code: str) -> str:
        async with httpx.AsyncClient(timeout=10, verify=self.verify_ssl) as client:
            # /oauth2/v1/token, not /oauth/token (404 on the deployed
            # server) and not the SPA's /api/v4/oauth2/token (rejects a
            # client_id/client_secret pair with "invalidClient" -- it
            # authenticates differently). Confirmed live against 5.5:
            # /oauth2/v1/token accepts this client's real credentials and
            # answers in RFC 6749's error shape, failing only on the code.
            response = await client.post(
                f"{self.base_url}/oauth2/v1/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            response.raise_for_status()
            return response.json()["access_token"]

    async def fetch_profile(self, access_token: str) -> TrueConfProfile:
        async with httpx.AsyncClient(timeout=10, verify=self.verify_ssl) as client:
            response = await client.get(
                f"{self.base_url}{self.userinfo_path}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            payload = response.json()
            subject = _dig(payload, self.subject_field)
            if subject is None:
                raise KeyError(f"{self.subject_field} missing from {self.userinfo_path} response")
            display = _dig(payload, self.display_field)
            return TrueConfProfile(
                subject=str(subject),
                display_label=str(display if display is not None else subject),
            )


def client_from_env() -> TrueConfOAuthClient:
    return TrueConfOAuthClient(
        base_url=os.environ["TRUECONF_BASE_URL"],
        client_id=os.environ["TRUECONF_OAUTH_CLIENT_ID"],
        client_secret=os.environ["TRUECONF_OAUTH_CLIENT_SECRET"],
        redirect_uri=os.environ["TRUECONF_OAUTH_REDIRECT_URI"],
        userinfo_path=os.environ.get("TRUECONF_USERINFO_PATH", "/api/v4/me"),
        subject_field=os.environ.get("TRUECONF_USERINFO_SUBJECT_FIELD", "user.id"),
        display_field=os.environ.get("TRUECONF_USERINFO_DISPLAY_FIELD", "user.display_name"),
        verify_ssl=os.environ.get("TRUECONF_VERIFY_SSL", "true").lower() != "false",
    )
