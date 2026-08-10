"""Explicit PostgreSQL UoW for durable billable Search attempt evidence."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from web_access.application.search.ports import (
    AttemptStage,
    SearchUsageUnavailable,
)
from web_access.domain.search import SearchProviderId


class PostgresSearchUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start_attempt(
        self,
        *,
        operation_id: str,
        principal_id: str,
        provider_id: SearchProviderId,
        query_item_index: int,
        attempt_number: int,
    ) -> None:
        try:
            await self._session.execute(
                text(
                    """
                    INSERT INTO search_provider_attempts (
                        operation_id, principal_id, provider_id, query_item_index,
                        attempt_number, stage
                    ) VALUES (
                        :operation_id, :principal_id, :provider_id, :query_item_index,
                        :attempt_number, 'pre_dispatch'
                    )
                    """
                ),
                {
                    "operation_id": operation_id,
                    "principal_id": principal_id,
                    "provider_id": provider_id.value,
                    "query_item_index": query_item_index,
                    "attempt_number": attempt_number,
                },
            )
        except SQLAlchemyError as exc:
            raise SearchUsageUnavailable("cannot create Search attempt evidence") from exc

    async def mark_stage(
        self,
        *,
        operation_id: str,
        provider_id: SearchProviderId,
        query_item_index: int,
        attempt_number: int,
        stage: AttemptStage,
        outcome_code: str | None = None,
        retry_reason: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        try:
            result = await self._session.execute(
                text(
                    """
                    UPDATE search_provider_attempts
                    SET stage = :stage,
                        outcome_code = COALESCE(:outcome_code, outcome_code),
                        retry_reason = COALESCE(:retry_reason, retry_reason),
                        provider_request_id = COALESCE(:provider_request_id, provider_request_id),
                        completed_at = CASE
                            WHEN :outcome_code IS NOT NULL THEN now()
                            ELSE completed_at
                        END
                    WHERE operation_id = :operation_id
                      AND provider_id = :provider_id
                      AND query_item_index = :query_item_index
                      AND attempt_number = :attempt_number
                      AND CASE stage
                            WHEN 'pre_dispatch' THEN 0
                            WHEN 'dispatch_possible' THEN 1
                            WHEN 'response_received' THEN 2
                            WHEN 'completed' THEN 3
                          END
                          <= CASE :stage
                            WHEN 'pre_dispatch' THEN 0
                            WHEN 'dispatch_possible' THEN 1
                            WHEN 'response_received' THEN 2
                            WHEN 'completed' THEN 3
                          END
                    """
                ),
                {
                    "operation_id": operation_id,
                    "provider_id": provider_id.value,
                    "query_item_index": query_item_index,
                    "attempt_number": attempt_number,
                    "stage": stage.value,
                    "outcome_code": outcome_code,
                    "retry_reason": retry_reason,
                    "provider_request_id": provider_request_id,
                },
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise SearchUsageUnavailable("Search attempt evidence was missing or stale")
        except SQLAlchemyError as exc:
            raise SearchUsageUnavailable("cannot update Search attempt evidence") from exc


class SqlAlchemySearchUsageUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._usage: PostgresSearchUsageRepository | None = None
        self._committed = False

    @property
    def usage(self) -> PostgresSearchUsageRepository:
        if self._usage is None:
            raise RuntimeError("Search usage unit of work is not active")
        return self._usage

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._usage = PostgresSearchUsageRepository(self._session)
        return self

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Search usage unit of work is not active")
        try:
            await self._session.commit()
            self._committed = True
        except SQLAlchemyError as exc:
            raise SearchUsageUnavailable("cannot commit Search attempt evidence") from exc

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None or not self._committed:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
            self._usage = None
            self._committed = False


class SqlAlchemySearchUsageUnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemySearchUsageUnitOfWork:
        return SqlAlchemySearchUsageUnitOfWork(self._session_factory)
