"""S9 durable attempt evidence against real PostgreSQL."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from web_access.application.search.ports import AttemptStage, SearchUsageUnavailable
from web_access.core.config import DatabaseSettings
from web_access.domain.search import SearchProviderId
from web_access.infrastructure.database import close_engine, create_engine, create_session_factory
from web_access.infrastructure.search import SqlAlchemySearchUsageUnitOfWorkFactory

pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.environ.get("WEB_ACCESS_TEST_DATABASE_URL")
    if not url:
        pytest.fail("WEB_ACCESS_TEST_DATABASE_URL is required for Search usage tests")
    return url


def _migrate() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _database_url())
    command.upgrade(config, "head")


@pytest.fixture(scope="module", autouse=True)
def migrated_schema() -> None:
    _migrate()


@pytest.mark.parametrize(
    ("provider", "item_index", "attempt", "stage"),
    [
        ("unknown", 0, 1, "pre_dispatch"),
        ("yandex", 32, 1, "pre_dispatch"),
        ("yandex", 0, 0, "pre_dispatch"),
        ("yandex", 0, 1, "unsafe_stage"),
    ],
)
@pytest.mark.asyncio
async def test_attempt_evidence_constraints_reject_unbounded_values(
    provider: str, item_index: int, attempt: int, stage: str
) -> None:
    engine = create_engine(DatabaseSettings.model_validate({"url": _database_url()}))
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO search_provider_attempts (
                            operation_id, principal_id, provider_id,
                            query_item_index, attempt_number, stage
                        ) VALUES ('constraint-op', 'principal', :provider, :item, :attempt, :stage)
                        """
                    ),
                    {
                        "provider": provider,
                        "item": item_index,
                        "attempt": attempt,
                        "stage": stage,
                    },
                )
    finally:
        await close_engine(engine)


@pytest.mark.asyncio
async def test_attempt_transitions_are_separately_committed_and_content_free() -> None:
    engine = create_engine(DatabaseSettings.model_validate({"url": _database_url()}))
    sessions = create_session_factory(engine)
    factory = SqlAlchemySearchUsageUnitOfWorkFactory(sessions)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE search_provider_attempts RESTART IDENTITY"))
    try:
        async with factory() as uow:
            await uow.usage.start_attempt(
                operation_id="operation-1",
                principal_id="principal-1",
                provider_id=SearchProviderId.YANDEX,
                query_item_index=0,
                attempt_number=1,
            )
            await uow.commit()

        async with sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT stage, completed_at, outcome_code "
                        "FROM search_provider_attempts WHERE operation_id='operation-1'"
                    )
                )
            ).one()
        assert tuple(row) == ("pre_dispatch", None, None)

        async with factory() as uow:
            await uow.usage.mark_stage(
                operation_id="operation-1",
                provider_id=SearchProviderId.YANDEX,
                query_item_index=0,
                attempt_number=1,
                stage=AttemptStage.DISPATCH_POSSIBLE,
            )
            await uow.commit()

        async with factory() as uow:
            await uow.usage.mark_stage(
                operation_id="operation-1",
                provider_id=SearchProviderId.YANDEX,
                query_item_index=0,
                attempt_number=1,
                stage=AttemptStage.COMPLETED,
                outcome_code="succeeded",
                provider_request_id="safe-provider-id",
            )
            await uow.commit()

        async with sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT stage, completed_at IS NOT NULL, outcome_code, provider_request_id "
                        "FROM search_provider_attempts WHERE operation_id='operation-1'"
                    )
                )
            ).one()
        assert tuple(row) == ("completed", True, "succeeded", "safe-provider-id")
    finally:
        await close_engine(engine)


@pytest.mark.asyncio
async def test_concurrent_duplicate_attempt_identity_has_one_durable_row() -> None:
    engine = create_engine(DatabaseSettings.model_validate({"url": _database_url()}))
    sessions = create_session_factory(engine)
    factory = SqlAlchemySearchUsageUnitOfWorkFactory(sessions)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE search_provider_attempts RESTART IDENTITY"))

    async def create() -> str:
        try:
            async with factory() as uow:
                await uow.usage.start_attempt(
                    operation_id="same-operation",
                    principal_id="principal",
                    provider_id=SearchProviderId.YANDEX,
                    query_item_index=3,
                    attempt_number=1,
                )
                await uow.commit()
            return "committed"
        except SearchUsageUnavailable:
            return "rejected"

    try:
        outcomes = await asyncio.gather(create(), create())
        assert sorted(outcomes) == ["committed", "rejected"]
        async with sessions() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM search_provider_attempts "
                    "WHERE operation_id='same-operation'"
                )
            )
        assert count == 1
    finally:
        await close_engine(engine)
