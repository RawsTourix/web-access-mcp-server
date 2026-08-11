"""Explicit SQLAlchemy Content repositories and Unit of Work."""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from web_access.application.content.ports import ContentRecord
from web_access.domain.content import (
    ContentFormat,
    ContentId,
    ContentObject,
    ContentRelation,
    ContentRelationType,
    ContentRepresentationKind,
    ContentState,
)
from web_access.infrastructure.database.models.content import ContentObjectRow, ContentRelationRow


def _content_from_row(row: ContentObjectRow) -> ContentObject:
    return ContentObject(
        content_id=ContentId(row.content_id),
        owner_principal_id=row.owner_principal_id,
        state=ContentState(row.state),
        revision=row.revision,
        representation_kind=ContentRepresentationKind(row.representation_kind),
        created_at=row.created_at,
        media_type=row.detected_media_type or row.declared_media_type,
        detected_format=ContentFormat(row.detected_format) if row.detected_format else None,
        source_filename=row.source_filename,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        expires_at=row.expires_at,
    )


def _record(row: ContentObjectRow) -> ContentRecord:
    return ContentRecord(
        content=_content_from_row(row),
        storage_key=row.storage_key,
        staging_key=row.staging_key,
        staged_at=row.staged_at,
        available_at=row.available_at,
        failure_code=row.failure_code,
    )


class PostgresContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, content: ContentObject) -> None:
        self._session.add(
            ContentObjectRow(
                content_id=str(content.content_id),
                owner_principal_id=content.owner_principal_id,
                state=content.state.value,
                revision=content.revision,
                representation_kind=content.representation_kind.value,
                declared_media_type=content.media_type,
                detected_format=(
                    content.detected_format.value if content.detected_format is not None else None
                ),
                source_filename=content.source_filename,
                size_bytes=content.size_bytes,
                sha256=content.sha256,
                created_at=content.created_at,
                updated_at=content.created_at,
                expires_at=content.expires_at,
            )
        )

    async def get(self, content_id: ContentId) -> ContentRecord | None:
        row = await self._session.scalar(
            select(ContentObjectRow).where(ContentObjectRow.content_id == str(content_id))
        )
        return None if row is None else _record(row)

    async def set_staged(
        self,
        content_id: ContentId,
        *,
        expected_revision: int,
        staging_key: str,
        sha256: str,
        size_bytes: int,
    ) -> ContentRecord | None:
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(ContentObjectRow)
            .where(
                ContentObjectRow.content_id == str(content_id),
                ContentObjectRow.state == ContentState.CREATING.value,
                ContentObjectRow.revision == expected_revision,
            )
            .values(
                staging_key=staging_key,
                sha256=sha256,
                size_bytes=size_bytes,
                staged_at=now,
                updated_at=now,
                revision=expected_revision + 1,
            )
            .returning(ContentObjectRow.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self.get(content_id)

    async def publish(
        self,
        content_id: ContentId,
        *,
        expected_revision: int,
        storage_key: str,
    ) -> ContentRecord | None:
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(ContentObjectRow)
            .where(
                ContentObjectRow.content_id == str(content_id),
                ContentObjectRow.state == ContentState.CREATING.value,
                ContentObjectRow.revision == expected_revision,
                ContentObjectRow.sha256.is_not(None),
                ContentObjectRow.size_bytes.is_not(None),
            )
            .values(
                state=ContentState.AVAILABLE.value,
                storage_key=storage_key,
                staging_key=None,
                available_at=now,
                updated_at=now,
                revision=expected_revision + 1,
            )
            .returning(ContentObjectRow.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self.get(content_id)

    async def mark_failed(
        self, content_id: ContentId, *, expected_revision: int, failure_code: str
    ) -> ContentRecord | None:
        now = datetime.now(UTC)
        result = await self._session.execute(
            update(ContentObjectRow)
            .where(
                ContentObjectRow.content_id == str(content_id),
                ContentObjectRow.state == ContentState.CREATING.value,
                ContentObjectRow.revision == expected_revision,
            )
            .values(
                state=ContentState.FAILED.value,
                failure_code=failure_code,
                updated_at=now,
                revision=expected_revision + 1,
            )
            .returning(ContentObjectRow.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self.get(content_id)


class PostgresContentRelationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, relation: ContentRelation) -> None:
        self._session.add(
            ContentRelationRow(
                source_content_id=str(relation.source_content_id),
                target_content_id=str(relation.target_content_id),
                relation_type=relation.relation_type.value,
                created_at=relation.created_at,
            )
        )

    async def for_source(self, source_content_id: ContentId) -> tuple[ContentRelation, ...]:
        rows = (
            await self._session.scalars(
                select(ContentRelationRow).where(
                    ContentRelationRow.source_content_id == str(source_content_id)
                )
            )
        ).all()
        return tuple(
            ContentRelation(
                source_content_id=ContentId(row.source_content_id),
                target_content_id=ContentId(row.target_content_id),
                relation_type=ContentRelationType(row.relation_type),
                created_at=row.created_at,
            )
            for row in rows
        )


class SqlAlchemyContentUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._contents: PostgresContentRepository | None = None
        self._relations: PostgresContentRelationRepository | None = None
        self._committed = False

    @property
    def contents(self) -> PostgresContentRepository:
        if self._contents is None:
            raise RuntimeError("Content unit of work is not active")
        return self._contents

    @property
    def relations(self) -> PostgresContentRelationRepository:
        if self._relations is None:
            raise RuntimeError("Content unit of work is not active")
        return self._relations

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._contents = PostgresContentRepository(self._session)
        self._relations = PostgresContentRelationRepository(self._session)
        return self

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Content unit of work is not active")
        await self._session.commit()
        self._committed = True

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
            self._contents = None
            self._relations = None
            self._committed = False


class SqlAlchemyContentUnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyContentUnitOfWork:
        return SqlAlchemyContentUnitOfWork(self._session_factory)
