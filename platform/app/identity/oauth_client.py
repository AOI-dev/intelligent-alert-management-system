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
        userinfo_path: str = "/api/v4/users/self",
        subject_field: str = "id",
        display_field: str = "displayName",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.userinfo_path = userinfo_path
        self.subject_field = subject_field
        self.display_field = display_field

    def authorize_url(self, state: str) -> str:
        params = httpx.QueryParams(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        return f"{self.base_url}/oauth/authorize?{params}"

    async def exchange_code(self, code: str) -> str:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/oauth/token",
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
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}{self.userinfo_path}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            payload = response.json()
            return TrueConfProfile(
                subject=str(payload[self.subject_field]),
                display_label=str(payload.get(self.display_field, payload[self.subject_field])),
            )


def client_from_env() -> TrueConfOAuthClient:
    return TrueConfOAuthClient(
        base_url=os.environ["TRUECONF_BASE_URL"],
        client_id=os.environ["TRUECONF_OAUTH_CLIENT_ID"],
        client_secret=os.environ["TRUECONF_OAUTH_CLIENT_SECRET"],
        redirect_uri=os.environ["TRUECONF_OAUTH_REDIRECT_URI"],
        userinfo_path=os.environ.get("TRUECONF_USERINFO_PATH", "/api/v4/users/self"),
        subject_field=os.environ.get("TRUECONF_USERINFO_SUBJECT_FIELD", "id"),
        display_field=os.environ.get("TRUECONF_USERINFO_DISPLAY_FIELD", "displayName"),
    )
