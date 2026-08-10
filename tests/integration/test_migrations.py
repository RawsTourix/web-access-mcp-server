from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


def _config() -> Config:
    if "WEB_ACCESS_TEST_DATABASE_URL" not in os.environ:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for migration tests")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["WEB_ACCESS_TEST_DATABASE_URL"])
    return config


async def _schema_state(url: str) -> tuple[set[str], str | None]:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    return tables, revision


async def _drop_version_table(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


def test_single_alembic_head() -> None:
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["0001_foundation"]


def test_empty_database_upgrade_is_repeatable_and_has_no_business_tables() -> None:
    config = _config()
    url = os.environ["WEB_ACCESS_TEST_DATABASE_URL"]
    asyncio.run(_drop_version_table(url))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    tables, revision = asyncio.run(_schema_state(url))
    assert tables == {"alembic_version"}
    assert revision == "0001_foundation"
