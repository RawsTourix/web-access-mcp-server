from __future__ import annotations

import pytest

from web_access.application.content.ports import ContentCursorClaims
from web_access.domain.content import ContentId
from web_access.infrastructure.content.cursor import HmacContentCursorCodec, InvalidContentCursor

CONTENT_ID = ContentId("cnt_0123456789abcdef0123456789abcdef")


def test_hmac_cursor_round_trip_is_versioned_opaque_and_bounded() -> None:
    codec = HmacContentCursorCodec("cursor-secret-a" * 4)
    claims = ContentCursorClaims("owner-a", CONTENT_ID, 7, 12345)

    cursor = codec.encode(claims)

    assert len(cursor) <= 2048
    assert "owner-a" not in cursor
    assert str(CONTENT_ID) not in cursor
    assert codec.decode(cursor) == claims


def test_hmac_cursor_rejects_tamper_and_wrong_deployment_secret() -> None:
    first = HmacContentCursorCodec("cursor-secret-a" * 4)
    second = HmacContentCursorCodec("cursor-secret-b" * 4)
    cursor = first.encode(ContentCursorClaims("owner-a", CONTENT_ID, 3, 8))
    replacement = "A" if cursor[-1] != "A" else "B"

    with pytest.raises(InvalidContentCursor):
        first.decode(cursor[:-1] + replacement)
    with pytest.raises(InvalidContentCursor):
        second.decode(cursor)
    with pytest.raises(InvalidContentCursor):
        first.decode("not-a-cursor")


def test_hmac_cursor_requires_dedicated_high_entropy_secret() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        HmacContentCursorCodec("short-secret")
