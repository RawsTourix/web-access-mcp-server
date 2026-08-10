"""Add durable billable Search attempt evidence.

Revision ID: 0002_search_attempts
Revises: 0001_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_search_attempts"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_provider_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("provider_id", sa.String(16), nullable=False),
        sa.Column("query_item_index", sa.SmallInteger(), nullable=False),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("outcome_code", sa.String(64), nullable=True),
        sa.Column("retry_reason", sa.String(64), nullable=True),
        sa.Column("provider_request_id", sa.String(256), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider_id IN ('searxng', 'yandex')", name="ck_search_attempt_provider"
        ),
        sa.CheckConstraint("query_item_index BETWEEN 0 AND 31", name="ck_search_attempt_item"),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 16", name="ck_search_attempt_number"),
        sa.CheckConstraint(
            "stage IN ('pre_dispatch', 'dispatch_possible', 'response_received', 'completed')",
            name="ck_search_attempt_stage",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "query_item_index",
            "provider_id",
            "attempt_number",
            name="uq_search_attempt_identity",
        ),
    )
    op.create_index(
        "ix_search_attempt_principal_started",
        "search_provider_attempts",
        ["principal_id", "started_at"],
    )
    op.create_index(
        "ix_search_attempt_provider_started",
        "search_provider_attempts",
        ["provider_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_attempt_provider_started", table_name="search_provider_attempts")
    op.drop_index("ix_search_attempt_principal_started", table_name="search_provider_attempts")
    op.drop_table("search_provider_attempts")
