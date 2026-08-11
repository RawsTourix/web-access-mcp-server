"""SQLAlchemy persistence models; never public application models."""

from web_access.infrastructure.database.models.content import ContentObjectRow, ContentRelationRow

__all__ = ["ContentObjectRow", "ContentRelationRow"]
