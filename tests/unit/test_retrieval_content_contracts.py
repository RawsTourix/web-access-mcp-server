from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from web_access.application.content.models import ContentRef, ParserDescriptor
from web_access.application.retrieval.models import RetrievalItemResult
from web_access.domain.content import (
    ContentFormat,
    ContentId,
    ContentObject,
    ContentRepresentationKind,
    ContentState,
    can_transition_content,
)
from web_access.domain.retrieval import (
    RetrievalBatchRequest,
    RetrievalProcessingLevel,
    RetrievalRequestItem,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
CONTENT_ID = "cnt_0123456789abcdef0123456789abcdef"
HASH = "a" * 64


def test_content_lifecycle_and_available_integrity_invariants() -> None:
    assert can_transition_content(ContentState.CREATING, ContentState.AVAILABLE)
    assert not can_transition_content(ContentState.AVAILABLE, ContentState.CREATING)
    content = ContentObject(
        content_id=ContentId(CONTENT_ID),
        owner_principal_id="agent",
        state=ContentState.AVAILABLE,
        revision=3,
        representation_kind=ContentRepresentationKind.RAW,
        created_at=NOW,
        size_bytes=0,
        sha256=HASH,
    )
    assert content.created_at == NOW
    with pytest.raises(ValueError, match="integrity"):
        ContentObject(
            content_id=ContentId(CONTENT_ID),
            owner_principal_id="agent",
            state=ContentState.AVAILABLE,
            revision=1,
            representation_kind=ContentRepresentationKind.RAW,
            created_at=NOW,
        )


def test_retrieval_batch_preserves_duplicates_and_bounds() -> None:
    item = RetrievalRequestItem("https://example.test/resource")
    batch = RetrievalBatchRequest((item, item), RetrievalProcessingLevel.INSPECT)
    assert batch.items == (item, item)
    with pytest.raises(ValueError, match="between 1 and 32"):
        RetrievalBatchRequest(())


def test_content_ref_serialization_has_no_storage_fields() -> None:
    reference = ContentRef(
        content_id=CONTENT_ID,
        media_type="text/plain",
        representation=ContentRepresentationKind.TEXT,
        size_bytes=5,
        sha256=HASH,
        created_at=NOW,
    )
    serialized = reference.model_dump(mode="json")
    assert serialized["content_id"] == CONTENT_ID
    assert not {"storage_key", "staging_key", "path"}.intersection(serialized)


def test_parser_descriptor_identity_and_format_uniqueness() -> None:
    descriptor = ParserDescriptor(
        capability="text.native",
        revision="text-native-v1",
        profile_revision="inline-bounded-v1",
        supported_formats=(ContentFormat.TEXT,),
        primary_representation=ContentRepresentationKind.TEXT,
        representation_schema_revision="text-v1",
    )
    assert descriptor.capability == "text.native"
    with pytest.raises(ValidationError, match="duplicate"):
        ParserDescriptor.model_validate(
            {
                **descriptor.model_dump(),
                "supported_formats": (ContentFormat.TEXT, ContentFormat.TEXT),
            }
        )


def test_retrieval_result_requires_raw_content_and_rejects_internal_fields() -> None:
    reference = ContentRef(
        content_id=CONTENT_ID,
        representation=ContentRepresentationKind.RAW,
        size_bytes=0,
        sha256=HASH,
        created_at=NOW,
    )
    result = RetrievalItemResult(
        requested_url="https://example.test",
        final_url="https://example.test",
        http_status=200,
        wire_bytes=0,
        entity_bytes=0,
        raw_content=reference,
    )
    assert result.raw_content == reference
    with pytest.raises(ValidationError):
        RetrievalItemResult.model_validate(
            {
                "requested_url": "https://example.test",
                "final_url": "https://example.test",
                "http_status": 200,
                "wire_bytes": 0,
                "entity_bytes": 0,
                "raw_content": reference,
                "storage_key": "secret/path",
            }
        )
