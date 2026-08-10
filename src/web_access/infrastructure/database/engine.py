"""Async PostgreSQL engine/session lifecycle."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from web_access.core.config import DatabaseSettings


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    return create_async_engine(
        str(settings.url),
        pool_pre_ping=True,
        pool_size=settings.pool_size,
        pool_timeout=settings.pool_timeout_seconds,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def probe_database(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:  # Infrastructure boundary intentionally normalizes driver failures.
        return False
    return True


async def close_engine(engine: AsyncEngine) -> None:
    await engine.dispose()
