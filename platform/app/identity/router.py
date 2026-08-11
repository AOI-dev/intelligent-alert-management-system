import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.db import get_session
from app.identity.dependencies import get_current_identity, require_role
from app.identity.models import Identity
from app.identity.oauth_client import TrueConfOAuthClient, client_from_env
from app.identity.repository import assign_role, get_or_provision_identity, link_ad_account, list_identities
from app.identity.session import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, issue_session_cookie

router = APIRouter(prefix="/v1/auth", tags=["auth"])
admin_router = APIRouter(prefix="/v1/identities", tags=["identities"])

_state_serializer = URLSafeTimedSerializer("oauth-state")


def _oauth_client() -> TrueConfOAuthClient:
    try:
        return client_from_env()
    except KeyError as error:
        raise HTTPException(status_code=503, detail=f"TrueConf OAuth not configured: {error}") from error


def _identity_out(identity: Identity) -> dict:
    return {
        "identity_id": str(identity.id),
        "display_label": identity.display_label,
        "roles": sorted(assignment.role_id for assignment in identity.roles),
        "ad_login": identity.ad_link.ad_login if identity.ad_link else None,
        "team": identity.ad_link.team if identity.ad_link else None,
        "department": identity.ad_link.department if identity.ad_link else None,
    }


@router.get("/login")
async def login() -> RedirectResponse:
    client = _oauth_client()
    state = _state_serializer.dumps(secrets.token_urlsafe(16))
    return RedirectResponse(client.authorize_url(state))


@router.get("/callback")
async def callback(
    code: str, state: str, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    try:
        _state_serializer.loads(state, max_age=600)
    except BadSignature as error:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from error

    client = _oauth_client()
    access_token = await client.exchange_code(code)
    profile = await client.fetch_profile(access_token)
    identity = await get_or_provision_identity(session, profile.subject, profile.display_label)

    response = RedirectResponse("/")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        issue_session_cookie(identity.id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/me")
async def me(identity: Identity = Depends(get_current_identity)) -> dict:
    return _identity_out(identity)


@admin_router.get("")
async def list_all_identities(
    session: AsyncSession = Depends(get_session),
    _: Identity = Depends(require_role("admin")),
) -> list[dict]:
    return [_identity_out(identity) for identity in await list_identities(session)]


class RoleAssignment(BaseModel):
    role_id: str


@admin_router.post("/{identity_id}/roles")
async def assign_identity_role(
    identity_id: UUID,
    body: RoleAssignment,
    session: AsyncSession = Depends(get_session),
    _: Identity = Depends(require_role("admin")),
) -> dict:
    identity = await assign_role(session, identity_id, body.role_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return _identity_out(identity)


class AdLinkRequest(BaseModel):
    ad_login: str
    department: str
    team: str
    manager_ad_login: str | None = None


@admin_router.put("/{identity_id}/ad-link")
async def link_identity_ad_account(
    identity_id: UUID,
    body: AdLinkRequest,
    session: AsyncSession = Depends(get_session),
    _: Identity = Depends(require_role("admin")),
) -> dict:
    identity = await link_ad_account(
        session, identity_id, body.ad_login, body.department, body.team, body.manager_ad_login
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")
    return _identity_out(identity)
