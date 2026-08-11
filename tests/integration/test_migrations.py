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
    assert heads == ["0003_content_core"]


def test_empty_database_upgrade_is_repeatable_and_content_scoped() -> None:
    config = _config()
    url = os.environ["WEB_ACCESS_TEST_DATABASE_URL"]
    command.downgrade(config, "base")
    asyncio.run(_drop_version_table(url))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    tables, revision = asyncio.run(_schema_state(url))
    assert tables == {
        "alembic_version",
        "search_provider_attempts",
        "content_objects",
        "content_relations",
    }
    assert revision == "0003_content_core"


def test_previous_accepted_v02_head_upgrades_to_v03_head() -> None:
    config = _config()
    url = os.environ["WEB_ACCESS_TEST_DATABASE_URL"]
    command.downgrade(config, "0002_search_attempts")
    tables, revision = asyncio.run(_schema_state(url))
    assert tables == {"alembic_version", "search_provider_attempts"}
    assert revision == "0002_search_attempts"
    command.upgrade(config, "head")
    tables, revision = asyncio.run(_schema_state(url))
    assert tables == {
        "alembic_version",
        "search_provider_attempts",
        "content_objects",
        "content_relations",
    }
    assert revision == "0003_content_core"


def test_attempt_schema_has_bounded_evidence_and_no_search_content() -> None:
    config = _config()
    command.upgrade(config, "head")
    url = os.environ["WEB_ACCESS_TEST_DATABASE_URL"]

    async def inspect_schema() -> tuple[set[str], set[str], set[tuple[str, ...]]]:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {
                    column["name"]
                    for column in inspect(sync).get_columns("search_provider_attempts")
                }
            )
            indexes = await connection.run_sync(
                lambda sync: {
                    index["name"]
                    for index in inspect(sync).get_indexes("search_provider_attempts")
                    if index["name"] is not None
                }
            )
            unique = await connection.run_sync(
                lambda sync: {
                    tuple(constraint["column_names"])
                    for constraint in inspect(sync).get_unique_constraints(
                        "search_provider_attempts"
                    )
                }
            )
        await engine.dispose()
        return columns, indexes, unique

    columns, indexes, unique = asyncio.run(inspect_schema())
    assert {"started_at", "completed_at", "stage", "outcome_code"} <= columns
    assert {
        "query",
        "query_hash",
        "title",
        "snippet",
        "result_body",
        "credential",
        "authorization",
    }.isdisjoint(columns)
    assert {"ix_search_attempt_principal_started", "ix_search_attempt_provider_started"} <= indexes
    assert (
        "operation_id",
        "query_item_index",
        "provider_id",
        "attempt_number",
    ) in unique


def test_content_schema_has_lifecycle_provenance_and_reuse_constraints() -> None:
    config = _config()
    command.upgrade(config, "head")
    url = os.environ["WEB_ACCESS_TEST_DATABASE_URL"]

    async def inspect_schema() -> tuple[set[str], set[str], set[str], set[str]]:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {
                    column["name"] for column in inspect(sync).get_columns("content_objects")
                }
            )
            indexes = await connection.run_sync(
                lambda sync: {
                    index["name"]
                    for index in inspect(sync).get_indexes("content_objects")
                    if index["name"] is not None
                }
            )
            checks = await connection.run_sync(
                lambda sync: {
                    check["name"]
                    for check in inspect(sync).get_check_constraints("content_objects")
                    if check["name"] is not None
                }
            )
            relation_foreign_keys = await connection.run_sync(
                lambda sync: {
                    next(iter(foreign_key["constrained_columns"]))
                    for foreign_key in inspect(sync).get_foreign_keys("content_relations")
                }
            )
        await engine.dispose()
        return columns, indexes, checks, relation_foreign_keys

    columns, indexes, checks, relation_foreign_keys = asyncio.run(inspect_schema())
    assert {
        "content_id",
        "owner_principal_id",
        "state",
        "revision",
        "storage_key",
        "staging_key",
        "source_content_id",
        "producer_capability",
        "producer_revision",
        "representation_schema_revision",
        "processing_profile_revision",
        "parameters_hash",
    } <= columns
    assert {
        "ix_content_owner_content",
        "ix_content_state_updated",
        "ix_content_storage_key",
        "ix_content_source",
        "uq_content_active_representation_identity",
    } <= indexes
    assert {
        "ck_content_state",
        "ck_content_available_integrity",
        "ck_content_derived_identity",
    } <= checks
    assert relation_foreign_keys == {"source_content_id", "target_content_id"}
