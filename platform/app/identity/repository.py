from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.identity.models import AdAccountLink, Identity, IdentityRole, Role

DEFAULT_ROLE = "viewer"
SEED_ROLES = {
    "viewer": "Read-only dashboard access scoped to the identity's team.",
    "engineer": "Acknowledge, assign, and override incidents for the identity's team.",
    "admin": "Manage routing rules, subscriptions, and role assignments.",
}


async def ensure_seed_roles(session: AsyncSession) -> None:
    existing = {role.id for role in (await session.execute(select(Role))).scalars()}
    for role_id, description in SEED_ROLES.items():
        if role_id not in existing:
            session.add(Role(id=role_id, description=description))
    await session.commit()


async def get_identity_by_id(session: AsyncSession, identity_id: UUID) -> Identity | None:
    stmt = (
        select(Identity)
        .where(Identity.id == identity_id)
        .options(selectinload(Identity.roles), selectinload(Identity.ad_link))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_provision_identity(session: AsyncSession, trueconf_subject: str, display_label: str) -> Identity:
    stmt = (
        select(Identity)
        .where(Identity.trueconf_subject == trueconf_subject)
        .options(selectinload(Identity.roles), selectinload(Identity.ad_link))
    )
    identity = (await session.execute(stmt)).scalar_one_or_none()
    if identity is not None:
        identity.last_login_at = datetime.now(timezone.utc)
        identity.display_label = display_label
        await session.commit()
        return identity

    identity = Identity(trueconf_subject=trueconf_subject, display_label=display_label)
    identity.roles.append(IdentityRole(role_id=DEFAULT_ROLE))
    session.add(identity)
    await session.commit()
    await session.refresh(identity, attribute_names=["roles", "ad_link"])
    return identity


async def list_identities(session: AsyncSession) -> list[Identity]:
    stmt = select(Identity).options(selectinload(Identity.roles), selectinload(Identity.ad_link))
    return list((await session.execute(stmt)).scalars())


async def assign_role(session: AsyncSession, identity_id: UUID, role_id: str) -> Identity:
    if await session.get(Role, role_id) is None:
        session.add(Role(id=role_id, description=""))
    existing = await session.get(IdentityRole, {"identity_id": identity_id, "role_id": role_id})
    if existing is None:
        session.add(IdentityRole(identity_id=identity_id, role_id=role_id))
    await session.commit()
    return await get_identity_by_id(session, identity_id)


async def link_ad_account(
    session: AsyncSession,
    identity_id: UUID,
    ad_login: str,
    department: str,
    team: str,
    manager_ad_login: str | None = None,
) -> Identity:
    link = await session.get(AdAccountLink, identity_id)
    if link is None:
        link = AdAccountLink(identity_id=identity_id, ad_login=ad_login, department=department, team=team)
        session.add(link)
    else:
        link.ad_login = ad_login
        link.department = department
        link.team = team
    link.manager_ad_login = manager_ad_login
    await session.commit()
    return await get_identity_by_id(session, identity_id)
