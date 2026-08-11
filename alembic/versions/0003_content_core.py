"""Add durable Content lifecycle, provenance, and reuse identity.

Revision ID: 0003_content_core
Revises: 0002_search_attempts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_content_core"
down_revision: str | Sequence[str] | None = "0002_search_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_objects",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("content_id", sa.String(128), nullable=False),
        sa.Column("owner_principal_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("representation_kind", sa.String(16), nullable=False),
        sa.Column("declared_media_type", sa.String(255)),
        sa.Column("detected_media_type", sa.String(255)),
        sa.Column("detected_format", sa.String(32)),
        sa.Column("source_filename", sa.String(255)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("storage_key", sa.String(255)),
        sa.Column("staging_key", sa.String(255)),
        sa.Column("inspection_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "source_content_id",
            sa.String(128),
            sa.ForeignKey("content_objects.content_id", ondelete="RESTRICT"),
        ),
        sa.Column("producer_capability", sa.String(64)),
        sa.Column("producer_revision", sa.String(128)),
        sa.Column("representation_schema_revision", sa.String(128)),
        sa.Column("processing_profile_revision", sa.String(128)),
        sa.Column("parameters_hash", sa.String(64)),
        sa.Column("source_provenance_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("staged_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(64)),
        sa.CheckConstraint(
            "state IN ('creating','available','failed','expired','deleted')",
            name="ck_content_state",
        ),
        sa.CheckConstraint(
            "representation_kind IN ('raw','text','markdown','structured','binary')",
            name="ck_content_representation_kind",
        ),
        sa.CheckConstraint("revision > 0", name="ck_content_revision_positive"),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_content_size"),
        sa.CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="ck_content_sha256"),
        sa.CheckConstraint(
            "parameters_hash IS NULL OR parameters_hash ~ '^[0-9a-f]{64}$'",
            name="ck_content_parameters_hash",
        ),
        sa.CheckConstraint(
            "(size_bytes IS NULL) = (sha256 IS NULL)", name="ck_content_integrity_pair"
        ),
        sa.CheckConstraint(
            "state <> 'available' OR (storage_key IS NOT NULL AND staging_key IS NULL "
            "AND size_bytes IS NOT NULL AND sha256 IS NOT NULL AND available_at IS NOT NULL)",
            name="ck_content_available_integrity",
        ),
        sa.CheckConstraint(
            "source_content_id IS NULL OR (producer_capability IS NOT NULL "
            "AND producer_revision IS NOT NULL AND representation_schema_revision IS NOT NULL "
            "AND processing_profile_revision IS NOT NULL AND parameters_hash IS NOT NULL)",
            name="ck_content_derived_identity",
        ),
        sa.UniqueConstraint("content_id", name="uq_content_objects_content_id"),
    )
    op.create_index(
        "ix_content_owner_content", "content_objects", ["owner_principal_id", "content_id"]
    )
    op.create_index("ix_content_state_updated", "content_objects", ["state", "updated_at"])
    op.create_index("ix_content_storage_key", "content_objects", ["storage_key"])
    op.create_index("ix_content_source", "content_objects", ["source_content_id"])
    op.create_index(
        "uq_content_active_representation_identity",
        "content_objects",
        [
            "owner_principal_id",
            "source_content_id",
            "producer_capability",
            "producer_revision",
            "processing_profile_revision",
            "parameters_hash",
            "representation_kind",
            "representation_schema_revision",
        ],
        unique=True,
        postgresql_where=sa.text(
            "source_content_id IS NOT NULL AND state IN ('creating','available')"
        ),
    )

    op.create_table(
        "content_relations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "source_content_id",
            sa.String(128),
            sa.ForeignKey("content_objects.content_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_content_id",
            sa.String(128),
            sa.ForeignKey("content_objects.content_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("relation_type IN ('derived_from')", name="ck_content_relation_type"),
        sa.CheckConstraint(
            "source_content_id <> target_content_id", name="ck_content_relation_not_self"
        ),
        sa.UniqueConstraint(
            "source_content_id",
            "target_content_id",
            "relation_type",
            name="uq_content_relation_identity",
        ),
    )
    op.create_index(
        "ix_content_relations_source",
        "content_relations",
        ["source_content_id", "created_at"],
    )
    op.create_index("ix_content_relations_target", "content_relations", ["target_content_id"])


def downgrade() -> None:
    op.drop_index("ix_content_relations_target", table_name="content_relations")
    op.drop_index("ix_content_relations_source", table_name="content_relations")
    op.drop_table("content_relations")
    op.drop_index("uq_content_active_representation_identity", table_name="content_objects")
    op.drop_index("ix_content_source", table_name="content_objects")
    op.drop_index("ix_content_storage_key", table_name="content_objects")
    op.drop_index("ix_content_state_updated", table_name="content_objects")
    op.drop_index("ix_content_owner_content", table_name="content_objects")
    op.drop_table("content_objects")
