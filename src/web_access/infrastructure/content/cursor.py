"""Versioned, integrity-protected stateless Content cursor codec."""

from __future__ import annotations

import base64
import hmac
import json

from web_access.application.content.ports import ContentCursorClaims
from web_access.domain.content import ContentId


class InvalidContentCursor(ValueError):
    pass


class HmacContentCursorCodec:
    _VERSION = 1

    def __init__(self, secret: str | bytes) -> None:
        encoded = secret.encode() if isinstance(secret, str) else secret
        if len(encoded) < 32:
            raise ValueError("Content cursor HMAC secret must contain at least 32 bytes")
        self._secret = encoded

    def encode(self, claims: ContentCursorClaims) -> str:
        payload = json.dumps(
            {
                "b": claims.byte_offset,
                "c": str(claims.content_id),
                "o": claims.owner_principal_id,
                "r": claims.content_revision,
                "v": self._VERSION,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.digest(self._secret, payload, "sha256")
        return f"{_encode(payload)}.{_encode(signature)}"

    def decode(self, cursor: str) -> ContentCursorClaims:
        if not cursor or len(cursor) > 2048:
            raise InvalidContentCursor("invalid Content cursor length")
        try:
            payload_value, signature_value = cursor.split(".", maxsplit=1)
            payload = _decode(payload_value)
            signature = _decode(signature_value)
        except (ValueError, UnicodeError) as error:
            raise InvalidContentCursor("malformed Content cursor") from error
        expected = hmac.digest(self._secret, payload, "sha256")
        if not hmac.compare_digest(signature, expected):
            raise InvalidContentCursor("Content cursor integrity check failed")
        try:
            value = json.loads(payload)
            if not isinstance(value, dict) or set(value) != {"b", "c", "o", "r", "v"}:
                raise ValueError("invalid claims")
            if value["v"] != self._VERSION:
                raise ValueError("unsupported version")
            owner = value["o"]
            revision = value["r"]
            offset = value["b"]
            if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
                raise ValueError("invalid owner")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ValueError("invalid revision")
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                raise ValueError("invalid offset")
            content_id = ContentId(value["c"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise InvalidContentCursor("invalid Content cursor claims") from error
        return ContentCursorClaims(
            owner_principal_id=owner,
            content_id=content_id,
            content_revision=revision,
            byte_offset=offset,
        )


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded
