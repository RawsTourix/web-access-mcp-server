"""Manual redirects plus hard bounded wire/entity streaming and decoding."""

from __future__ import annotations

import asyncio
import re
import zlib
from collections.abc import AsyncIterator
from email.message import Message
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from aiohttp import ClientError, ClientPayloadError, ClientResponse

from web_access.application.common.context import ExecutionContext
from web_access.application.retrieval.ports import (
    DecompressionLimitExceeded,
    FetchCounters,
    RedirectBlocked,
    ResponseTooLarge,
    RetrievalConnectionError,
    RetrievalPolicyError,
    SafeFetchResponse,
    TooManyRedirects,
    UnsupportedContentEncoding,
)
from web_access.core.config import RetrievalSettings
from web_access.domain.retrieval import RedirectHop
from web_access.infrastructure.retrieval.client import SafeAioHttpClient
from web_access.infrastructure.retrieval.security import (
    BlockedDestinationError,
    InvalidRetrievalUrl,
    RetrievalUrlPolicy,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SAFE_MEDIA = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


class _Decompressor(Protocol):
    @property
    def eof(self) -> bool: ...

    def decompress(self, data: bytes, max_length: int = 0, /) -> bytes: ...

    def flush(self, length: int = ..., /) -> bytes: ...


def _has_cause(error: BaseException, expected: type[BaseException]) -> bool:
    observed: BaseException | None = error
    visited: set[int] = set()
    while observed is not None and id(observed) not in visited:
        if isinstance(observed, expected):
            return True
        visited.add(id(observed))
        observed = observed.__cause__ or observed.__context__
    return False


class SafeHttpFetcher:
    def __init__(
        self,
        *,
        client: SafeAioHttpClient,
        policy: RetrievalUrlPolicy,
        settings: RetrievalSettings,
    ) -> None:
        self._client = client
        self._policy = policy
        self._settings = settings

    async def fetch(self, context: ExecutionContext, url: str) -> SafeFetchResponse:
        requested_url = url
        current_url = url
        redirects: list[RedirectHop] = []
        while True:
            try:
                self._policy.validate_url(current_url)
                response = await self._client.get(
                    current_url,
                    timeout_seconds=self._remaining_timeout(context),
                )
            except (BlockedDestinationError, InvalidRetrievalUrl) as error:
                raise RetrievalPolicyError("Retrieval destination is blocked") from error
            except TimeoutError:
                raise
            except (ClientError, OSError) as error:
                if redirects and _has_cause(error, BlockedDestinationError):
                    raise RedirectBlocked(
                        "redirect target resolved to a blocked address"
                    ) from error
                raise RetrievalConnectionError("Retrieval connection failed") from error
            if response.status not in _REDIRECT_STATUSES:
                return self._response(requested_url, current_url, redirects, response)
            location = response.headers.get("Location")
            if not location:
                return self._response(requested_url, current_url, redirects, response)
            if len(redirects) >= self._settings.max_redirects:
                response.close()
                raise TooManyRedirects("redirect count exceeded")
            if len(location) > 8192:
                response.close()
                raise RedirectBlocked("redirect location exceeds URL bound")
            target = urljoin(current_url, location)
            try:
                validated = self._policy.validate_url(target)
            except (BlockedDestinationError, ValueError) as error:
                response.close()
                raise RedirectBlocked("redirect target is blocked") from error
            redirects.append(
                RedirectHop(
                    status=response.status,
                    from_url=current_url,
                    to_url=validated.normalized_url,
                )
            )
            response.close()
            current_url = validated.normalized_url

    def _response(
        self,
        requested_url: str,
        current_url: str,
        redirects: list[RedirectHop],
        response: ClientResponse,
    ) -> SafeFetchResponse:
        length = response.content_length
        if length is not None and length > self._settings.max_wire_bytes:
            response.close()
            raise ResponseTooLarge("Content-Length exceeds wire limit")
        encoding = self._content_encoding(response)
        counters = FetchCounters()
        return SafeFetchResponse(
            requested_url=requested_url,
            final_url=str(response.url) if response.url else current_url,
            http_status=response.status,
            redirect_chain=tuple(redirects),
            content_encoding=encoding,
            declared_media_type=_declared_media_type(response.headers.get("Content-Type")),
            source_filename=(
                _source_filename(response.headers.get("Content-Disposition"))
                or _source_filename_from_url(str(response.url))
            ),
            body=self._body(response, encoding, counters),
            counters=counters,
        )

    def _content_encoding(self, response: ClientResponse) -> str | None:
        value = response.headers.get("Content-Encoding")
        if value is None or value.strip().lower() in {"", "identity"}:
            return None
        normalized = value.strip().lower()
        if normalized not in {"gzip", "x-gzip", "deflate"}:
            response.close()
            raise UnsupportedContentEncoding("unsupported Content-Encoding")
        return "gzip" if normalized == "x-gzip" else normalized

    async def _body(
        self,
        response: ClientResponse,
        encoding: str | None,
        counters: FetchCounters,
    ) -> AsyncIterator[bytes]:
        decoder = _decoder(encoding)
        try:
            while not response.content.at_eof():
                async with asyncio.timeout(self._settings.read_inactivity_seconds):
                    wire = await response.content.read(self._settings.stream_chunk_size)
                if not wire:
                    break
                counters.wire_bytes += len(wire)
                if counters.wire_bytes > self._settings.max_wire_bytes:
                    raise ResponseTooLarge("wire byte limit exceeded")
                entity = self._decode_chunk(decoder, wire, counters)
                if entity:
                    yield entity
            if decoder is not None:
                remaining = self._settings.max_entity_bytes - counters.entity_bytes + 1
                tail = decoder.flush(max(1, remaining))
                self._account_entity(tail, counters)
                if not decoder.eof:
                    raise ClientPayloadError("compressed response ended before stream completion")
                if tail:
                    yield tail
            self._check_ratio(counters)
        except TimeoutError:
            raise
        except (zlib.error, ClientPayloadError, OSError) as error:
            raise RetrievalConnectionError("invalid or incomplete response body") from error
        finally:
            response.close()

    def _decode_chunk(
        self,
        decoder: _Decompressor | None,
        wire: bytes,
        counters: FetchCounters,
    ) -> bytes:
        if decoder is None:
            entity = wire
        else:
            remaining = self._settings.max_entity_bytes - counters.entity_bytes + 1
            entity = decoder.decompress(wire, max(1, remaining))
        self._account_entity(entity, counters)
        self._check_ratio(counters)
        return entity

    def _account_entity(self, entity: bytes, counters: FetchCounters) -> None:
        counters.entity_bytes += len(entity)
        if counters.entity_bytes > self._settings.max_entity_bytes:
            raise DecompressionLimitExceeded("entity byte limit exceeded")

    def _check_ratio(self, counters: FetchCounters) -> None:
        if counters.wire_bytes and (
            counters.entity_bytes / counters.wire_bytes > self._settings.max_decompression_ratio
        ):
            raise DecompressionLimitExceeded("decompression ratio limit exceeded")

    def _remaining_timeout(self, context: ExecutionContext) -> float:
        remaining = context.remaining_seconds()
        if remaining is None:
            return self._settings.operation_timeout_seconds
        if remaining <= 0:
            raise TimeoutError("Retrieval operation deadline expired")
        return remaining


def _decoder(encoding: str | None) -> _Decompressor | None:
    if encoding == "gzip":
        return zlib.decompressobj(zlib.MAX_WBITS | 16)
    if encoding == "deflate":
        return zlib.decompressobj(zlib.MAX_WBITS)
    return None


def _declared_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media if len(media) <= 255 and _SAFE_MEDIA.fullmatch(media) else None


def _source_filename(value: str | None) -> str | None:
    if value is None or len(value) > 4096:
        return None
    message = Message()
    message["Content-Disposition"] = value
    filename = message.get_filename()
    if filename is None:
        return None
    return _safe_filename(filename)


def _source_filename_from_url(value: str) -> str | None:
    path = urlsplit(value).path
    return _safe_filename(path.rsplit("/", 1)[-1]) if path else None


def _safe_filename(filename: str) -> str | None:
    safe = "".join(
        "_" if character in {"/", "\\"} or ord(character) < 32 else character
        for character in filename
    ).strip(" .")
    return safe[:255] or None
