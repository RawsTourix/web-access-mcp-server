"""SQLAlchemy Content metadata and provenance rows."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from web_access.infrastructure.database.base import Base


class ContentObjectRow(Base):
    __tablename__ = "content_objects"
    __table_args__ = (
        UniqueConstraint("content_id", name="uq_content_objects_content_id"),
        Index("ix_content_owner_content", "owner_principal_id", "content_id"),
        Index("ix_content_state_updated", "state", "updated_at"),
        Index("ix_content_storage_key", "storage_key"),
        Index("ix_content_source", "source_content_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    content_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    representation_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    declared_media_type: Mapped[str | None] = mapped_column(String(255))
    detected_media_type: Mapped[str | None] = mapped_column(String(255))
    detected_format: Mapped[str | None] = mapped_column(String(32))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(255))
    staging_key: Mapped[str | None] = mapped_column(String(255))
    inspection_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    source_content_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("content_objects.content_id", ondelete="RESTRICT")
    )
    producer_capability: Mapped[str | None] = mapped_column(String(64))
    producer_revision: Mapped[str | None] = mapped_column(String(128))
    representation_schema_revision: Mapped[str | None] = mapped_column(String(128))
    processing_profile_revision: Mapped[str | None] = mapped_column(String(128))
    parameters_hash: Mapped[str | None] = mapped_column(String(64))
    source_provenance_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    staged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))


class ContentRelationRow(Base):
    __tablename__ = "content_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_content_id",
            "target_content_id",
            "relation_type",
            name="uq_content_relation_identity",
        ),
        Index("ix_content_relations_source", "source_content_id", "created_at"),
        Index("ix_content_relations_target", "target_content_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_content_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("content_objects.content_id", ondelete="CASCADE"), nullable=False
    )
    target_content_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("content_objects.content_id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
