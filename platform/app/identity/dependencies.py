from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.db import get_session
from app.identity.models import Identity
from app.identity.repository import get_identity_by_id
from app.identity.session import SESSION_COOKIE_NAME, read_session_cookie


def _token_from_request(request: Request) -> str | None:
    """The same signed token works as either a same-host cookie or a
    cross-origin Authorization: Bearer header -- see
    app/identity/router.py's callback and return_to.py for why a bearer
    token exists at all (a cookie set during the TrueConf OAuth callback
    is only ever valid for that one fixed host). Cookie checked first
    since it's the common case (deployed frontend, same host as the API);
    the header is what a cross-origin frontend sends instead.
    """
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        return cookie
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[len("bearer ") :]
    return None


async def get_current_identity(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Identity:
    token = _token_from_request(request)
    identity_id = read_session_cookie(token) if token else None
    if identity_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    identity = await get_identity_by_id(session, identity_id)
    if identity is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return identity


def require_role(*allowed_roles: str):
    async def dependency(identity: Identity = Depends(get_current_identity)) -> Identity:
        identity_roles = {assignment.role_id for assignment in identity.roles}
        if identity_roles.isdisjoint(allowed_roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return identity

    return dependency
