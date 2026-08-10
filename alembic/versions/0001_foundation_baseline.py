"""Establish the empty v0.1 migration baseline.

Revision ID: 0001_foundation
Revises: None
"""

from collections.abc import Sequence

revision: str = "0001_foundation"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No business tables exist in Service Foundation."""


def downgrade() -> None:
    """The empty baseline has no schema objects to remove."""
