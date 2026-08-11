from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.db import get_session
from app.identity.models import Identity
from app.identity.repository import get_identity_by_id
from app.identity.session import SESSION_COOKIE_NAME, read_session_cookie


async def get_current_identity(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Identity:
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    identity_id = read_session_cookie(cookie) if cookie else None
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
