"""Dependency-free Retrieval value models and invariants."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class RetrievalProcessingLevel(StrEnum):
    STORE_ONLY = "store_only"
    INSPECT = "inspect"
    NATIVE = "native"


class RetrievalExecutionPhase(StrEnum):
    VALIDATED = "validated"
    DNS_RESOLVING = "dns_resolving"
    CONNECTING = "connecting"
    DISPATCH_POSSIBLE = "dispatch_possible"
    RESPONSE_HEADERS = "response_headers"
    BODY_STREAMING = "body_streaming"
    CONTENT_CREATING = "content_creating"
    CONTENT_STAGING = "content_staging"
    CONTENT_FINALIZED = "content_finalized"
    PROCESSING = "processing"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class RetrievalRequestItem:
    url: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.url) <= 8192:
            raise ValueError("Retrieval URL length must be between 1 and 8192")
        parsed = urlsplit(self.url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("Retrieval URL must use HTTP or HTTPS")
        if not parsed.hostname:
            raise ValueError("Retrieval URL requires a hostname")


@dataclass(frozen=True, slots=True)
class RetrievalBatchRequest:
    items: tuple[RetrievalRequestItem, ...]
    processing_level: RetrievalProcessingLevel = RetrievalProcessingLevel.NATIVE

    def __post_init__(self) -> None:
        if not 1 <= len(self.items) <= 32:
            raise ValueError("Retrieval batch must contain between 1 and 32 items")


@dataclass(frozen=True, slots=True)
class RedirectHop:
    status: int
    from_url: str
    to_url: str

    def __post_init__(self) -> None:
        if not 300 <= self.status <= 399:
            raise ValueError("redirect status must be a 3xx response")
        if len(self.from_url) > 8192 or len(self.to_url) > 8192:
            raise ValueError("redirect URL exceeds provenance bound")


@dataclass(frozen=True, slots=True)
class RetrievedResource:
    requested_url: str
    final_url: str
    http_status: int
    redirect_chain: tuple[RedirectHop, ...]
    wire_bytes: int
    entity_bytes: int
    content_encoding: str | None = None
    declared_media_type: str | None = None
    source_filename: str | None = None

    def __post_init__(self) -> None:
        if not 100 <= self.http_status <= 599:
            raise ValueError("invalid HTTP status")
        if self.wire_bytes < 0 or self.entity_bytes < 0:
            raise ValueError("Retrieval byte counters cannot be negative")
        if len(self.redirect_chain) > 10:
            raise ValueError("redirect chain exceeds bounded model")
