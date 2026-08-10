"""Bounded official SearXNG JSON Search API adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from web_access.application.common.context import ExecutionContext
from web_access.application.common.errors import ErrorCategory, OperationError
from web_access.application.common.hints import Warning
from web_access.application.common.results import ExecutionStage
from web_access.application.search.models import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
)
from web_access.application.search.ports import ProviderAttemptError
from web_access.core.config import SearxngSettings
from web_access.domain.search import SearchProviderId, SearchResultItem, SearchSafeMode

_SAFE_SEARCH = {
    SearchSafeMode.OFF: "0",
    SearchSafeMode.MODERATE: "1",
    SearchSafeMode.STRICT: "2",
}


class SearxngSearchProvider:
    """Execute one SearXNG request per call without hidden retries."""

    def __init__(self, settings: SearxngSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self.descriptor = ProviderDescriptor(
            provider_id=SearchProviderId.SEARXNG,
            name="SearXNG",
            enabled=settings.enabled,
            configuration_revision=_configuration_revision(settings),
            capabilities=ProviderCapabilities(
                pagination=True,
                language=True,
                region=False,
                safe_search=True,
                time_range=True,
                max_results=settings.max_results,
                billable=False,
            ),
        )

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        if request.provider_id is not SearchProviderId.SEARXNG:
            raise ValueError("SearXNG provider received a request for another provider")
        timeout = self._timeout(context)
        params: dict[str, str] = {
            "q": request.query,
            "format": "json",
            "categories": "general",
            "pageno": str(request.page),
        }
        if request.language is not None:
            params["language"] = str(request.language)
        if request.safe_search is not None:
            params["safesearch"] = _SAFE_SEARCH[request.safe_search]
        if request.time_range is not None:
            params["time_range"] = request.time_range.value

        response: httpx.Response | None = None
        try:
            async with self._client.stream(
                "GET",
                str(self._settings.endpoint).rstrip("/") + "/search",
                params=params,
                timeout=httpx.Timeout(timeout),
            ) as response:
                request_id = _request_id(response.headers)
                if response.status_code >= 400:
                    raise _status_error(response.status_code, response.headers, request_id)
                body = await _bounded_body(response, self._settings.max_response_bytes)
        except ProviderAttemptError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise _attempt_error(
                ErrorCategory.UPSTREAM,
                "searxng_unavailable",
                "SearXNG is unavailable",
                retryable=True,
                stage=ExecutionStage.BEFORE_DISPATCH,
            ) from exc
        except httpx.TimeoutException as exc:
            raise _attempt_error(
                ErrorCategory.TIMEOUT,
                "searxng_timeout",
                "SearXNG did not respond before the deadline",
                retryable=True,
                stage=ExecutionStage.RESPONSE_LOST,
            ) from exc
        except httpx.TransportError as exc:
            raise _attempt_error(
                ErrorCategory.UPSTREAM,
                "searxng_transport_error",
                "SearXNG transport failed",
                retryable=True,
                stage=ExecutionStage.RESPONSE_LOST,
            ) from exc

        request_id = _request_id(response.headers) if response is not None else None
        payload = _decode_payload(body, request_id)
        results = _parse_results(payload, request.limit, request_id)
        warnings = _parse_warnings(payload)
        return ProviderSearchResult(
            provider_id=SearchProviderId.SEARXNG,
            results=results,
            retrieved_at=context.clock.utc_now(),
            next_page_available=None,
            provider_request_id=request_id,
            warnings=warnings,
        )

    def _timeout(self, context: ExecutionContext) -> float:
        remaining = context.remaining_seconds()
        if remaining is None:
            return self._settings.request_timeout_seconds
        if remaining <= 0:
            raise _attempt_error(
                ErrorCategory.TIMEOUT,
                "search_deadline_exceeded",
                "Search deadline was exceeded before dispatch",
                retryable=False,
                stage=ExecutionStage.BEFORE_DISPATCH,
            )
        return min(remaining, self._settings.request_timeout_seconds)


async def _bounded_body(response: httpx.Response, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > maximum:
            raise _attempt_error(
                ErrorCategory.UPSTREAM,
                "searxng_response_too_large",
                "SearXNG response exceeded the configured bound",
                retryable=False,
                stage=ExecutionStage.TERMINAL_KNOWN,
                provider_request_id=_request_id(response.headers),
            )
        body.extend(chunk)
    return bytes(body)


def _decode_payload(body: bytes, request_id: str | None) -> Mapping[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _malformed(request_id) from exc
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise _malformed(request_id)
    return value


def _parse_results(
    payload: Mapping[str, Any], limit: int, request_id: str | None
) -> tuple[SearchResultItem, ...]:
    parsed: list[SearchResultItem] = []
    for raw in payload["results"][:limit]:
        if not isinstance(raw, dict):
            raise _malformed(request_id)
        title = raw.get("title")
        url = raw.get("url")
        snippet = raw.get("content")
        if (
            not isinstance(title, str)
            or not title
            or len(title) > 4096
            or not isinstance(url, str)
            or not url
            or len(url) > 8192
            or (snippet is not None and (not isinstance(snippet, str) or len(snippet) > 8192))
        ):
            raise _malformed(request_id)
        split = urlsplit(url)
        if split.scheme not in {"http", "https"} or split.hostname is None:
            raise _malformed(request_id)
        published_at = _published_at(raw.get("publishedDate"))
        parsed.append(
            SearchResultItem(
                rank=len(parsed) + 1,
                title=title,
                url=url,
                snippet=snippet,
                host=split.hostname[:1024],
                published_at=published_at,
            )
        )
    return tuple(parsed)


def _published_at(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _parse_warnings(payload: Mapping[str, Any]) -> tuple[Warning, ...]:
    unavailable = payload.get("unresponsive_engines")
    if not isinstance(unavailable, list) or not unavailable:
        return ()
    return (
        Warning(
            code="partial_provider_failure",
            message="Some SearXNG engines did not return results",
            details={"engine_failure_count": min(len(unavailable), 1000)},
        ),
    )


def _status_error(
    status: int, headers: httpx.Headers, request_id: str | None
) -> ProviderAttemptError:
    if status == 429:
        retry_after = _retry_after(headers)
        return _attempt_error(
            ErrorCategory.RATE_LIMITED,
            "searxng_rate_limited",
            "SearXNG rate limit was reached",
            retryable=True,
            retry_after_seconds=retry_after,
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )
    if status >= 500:
        return _attempt_error(
            ErrorCategory.UPSTREAM,
            "searxng_upstream_error",
            "SearXNG returned an upstream error",
            retryable=True,
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )
    return _attempt_error(
        ErrorCategory.UPSTREAM,
        "searxng_request_rejected",
        "SearXNG rejected the request",
        retryable=False,
        stage=ExecutionStage.TERMINAL_KNOWN,
        provider_request_id=request_id,
    )


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    if value is None or not value.isdecimal():
        return None
    return min(int(value), 86400)


def _request_id(headers: httpx.Headers) -> str | None:
    value = headers.get("x-request-id") or headers.get("x-correlation-id")
    return value[:256] if value else None


def _malformed(request_id: str | None) -> ProviderAttemptError:
    return _attempt_error(
        ErrorCategory.UPSTREAM,
        "searxng_malformed_response",
        "SearXNG returned a malformed response",
        retryable=False,
        stage=ExecutionStage.TERMINAL_KNOWN,
        provider_request_id=request_id,
    )


def _attempt_error(
    category: ErrorCategory,
    code: str,
    message: str,
    *,
    retryable: bool,
    stage: ExecutionStage,
    retry_after_seconds: int | None = None,
    provider_request_id: str | None = None,
) -> ProviderAttemptError:
    return ProviderAttemptError(
        OperationError(
            category=category,
            code=code,
            message=message,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        ),
        stage=stage,
        provider_request_id=provider_request_id,
    )


def _configuration_revision(settings: SearxngSettings) -> str:
    canonical = json.dumps(
        settings.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
