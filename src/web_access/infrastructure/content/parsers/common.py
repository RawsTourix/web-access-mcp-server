"""Shared bounded parser helpers and normalized failures."""

from __future__ import annotations

import json


class NativeParserError(ValueError):
    code = "native_parse_failed"


class ParserInputLimitExceeded(NativeParserError):
    code = "parser_input_limit"


class ParserOutputLimitExceeded(NativeParserError):
    code = "parser_output_limit"


class ParserDepthLimitExceeded(NativeParserError):
    code = "parser_depth_limit"


def require_input_bound(data: bytes, limit: int) -> None:
    if len(data) > limit:
        raise ParserInputLimitExceeded("parser input exceeds configured limit")


def bounded_json_bytes(value: object, limit: int) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if len(encoded) > limit:
        raise ParserOutputLimitExceeded("parser output exceeds configured limit")
    return encoded


def json_depth(value: object, limit: int, *, depth: int = 1) -> int:
    if depth > limit:
        raise ParserDepthLimitExceeded("structured value exceeds depth limit")
    if isinstance(value, dict):
        return max(
            (json_depth(item, limit, depth=depth + 1) for item in value.values()),
            default=depth,
        )
    if isinstance(value, list):
        return max(
            (json_depth(item, limit, depth=depth + 1) for item in value),
            default=depth,
        )
    return depth
