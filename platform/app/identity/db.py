import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.identity.models import Base

DATABASE_URL = os.environ.get(
    "IDENTITY_DATABASE_URL",
    "postgresql+asyncpg://platform:platform@timescaledb:5432/platform",
)

_engine: AsyncEngine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


async def init_models() -> None:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    await _engine.dispose()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
