from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from web_access.core.config import DatabaseSettings
from web_access.infrastructure.database import (
    SqlAlchemyUnitOfWorkFactory,
    close_engine,
    create_engine,
    create_session_factory,
    probe_database,
)

pytestmark = pytest.mark.integration


def _database_settings() -> DatabaseSettings:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if not url:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return DatabaseSettings.model_validate({"url": url})


@pytest.mark.asyncio
async def test_health_and_explicit_uow_semantics() -> None:
    engine = create_engine(_database_settings())
    factory = create_session_factory(engine)
    uow_factory = SqlAlchemyUnitOfWorkFactory(factory)
    assert await probe_database(engine)
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS foundation_uow_probe"))
        await connection.execute(
            text("CREATE TABLE foundation_uow_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        )
    try:
        async with uow_factory() as uow:
            await uow.session.execute(
                text("INSERT INTO foundation_uow_probe (id, value) VALUES (1, 'committed')")
            )
            await uow.commit()
        async with factory() as session:
            assert (
                await session.scalar(text("SELECT value FROM foundation_uow_probe WHERE id = 1"))
                == "committed"
            )

        async with uow_factory() as uow:
            await uow.session.execute(
                text("INSERT INTO foundation_uow_probe (id, value) VALUES (2, 'rolled-back')")
            )
        async with factory() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM foundation_uow_probe WHERE id = 2"))
                == 0
            )

        with pytest.raises(RuntimeError, match="synthetic failure"):
            async with uow_factory() as uow:
                await uow.session.execute(
                    text("INSERT INTO foundation_uow_probe (id, value) VALUES (3, 'exception')")
                )
                raise RuntimeError("synthetic failure")
        async with factory() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM foundation_uow_probe WHERE id = 3"))
                == 0
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS foundation_uow_probe"))
        await close_engine(engine)


@pytest.mark.asyncio
async def test_concurrent_sessions_are_isolated() -> None:
    engine = create_engine(_database_settings())
    factory = create_session_factory(engine)
    try:
        async with factory() as first, factory() as second:
            first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
            second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
            assert first_pid != second_pid
    finally:
        await close_engine(engine)
