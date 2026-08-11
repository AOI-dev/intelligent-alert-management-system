"""Identity persistence: TrueConf-authenticated identities, an open-ended
role table (not a fixed enum — new roles are rows, not code changes), and a
synthetic Active Directory link used only as a nominal attribute source
(team/department), never as an auth path. See АР-07 in
artifacts/requirements-traceability.md.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    __tablename__ = "roles"

    # The slug is the role: "viewer" / "engineer" / "admin" are seed data,
    # not a hardcoded enum. Adding a role is an insert, not a deploy.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Identity(Base):
    __tablename__ = "identities"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    trueconf_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_label: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    roles: Mapped[list["IdentityRole"]] = relationship(back_populates="identity", cascade="all, delete-orphan")
    ad_link: Mapped["AdAccountLink | None"] = relationship(back_populates="identity", cascade="all, delete-orphan", uselist=False)


class IdentityRole(Base):
    __tablename__ = "identity_roles"

    identity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("identities.id"), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(64), ForeignKey("roles.id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    identity: Mapped[Identity] = relationship(back_populates="roles")


class AdAccountLink(Base):
    """A nominal Active Directory attribute source (АР-07): department/team
    context for routing, not a real AD trust. All values are synthetic in
    the pilot; see scripts populated by identity/seed.py.
    """

    __tablename__ = "ad_account_links"

    identity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("identities.id"), primary_key=True)
    ad_login: Mapped[str] = mapped_column(String(255), unique=True)
    department: Mapped[str] = mapped_column(String(255))
    team: Mapped[str] = mapped_column(String(255))
    manager_ad_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

    identity: Mapped[Identity] = relationship(back_populates="ad_link")
