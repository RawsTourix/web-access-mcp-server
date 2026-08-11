"""Direct bounded Yandex Search API v2 synchronous REST adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree

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
from web_access.core.config import YandexSearchSettings
from web_access.domain.search import (
    SearchProviderId,
    SearchResultItem,
    SearchSafeMode,
    SearchTimeRange,
)

_SAFE_SEARCH = {
    SearchSafeMode.OFF: "FAMILY_MODE_NONE",
    SearchSafeMode.MODERATE: "FAMILY_MODE_MODERATE",
    SearchSafeMode.STRICT: "FAMILY_MODE_STRICT",
}
_PERIOD = {
    SearchTimeRange.DAY: "PERIOD_DAY",
    SearchTimeRange.MONTH: "PERIOD_MONTH",
}
_REGION_SEARCH_TYPES = {"SEARCH_TYPE_RU", "SEARCH_TYPE_TR"}
_WHITESPACE = re.compile(r"\s+")


class YandexSearchProvider:
    """Execute exactly one official synchronous Yandex REST attempt per call."""

    def __init__(self, settings: YandexSearchSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self.descriptor = ProviderDescriptor(
            provider_id=SearchProviderId.YANDEX,
            name="Yandex Search API",
            enabled=settings.enabled,
            configuration_revision=_configuration_revision(settings),
            capabilities=ProviderCapabilities(
                pagination=True,
                language=False,
                region=settings.search_type in _REGION_SEARCH_TYPES,
                safe_search=True,
                time_range=True,
                supported_time_ranges=(SearchTimeRange.DAY, SearchTimeRange.MONTH),
                max_results=settings.max_results,
                max_query_length=400,
                max_query_words=40,
                max_result_window=250,
                billable=True,
            ),
        )

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        self._validate_request(request)
        timeout = self._timeout(context)
        folder_id = self._settings.folder_id
        api_key = self._settings.api_key
        if folder_id is None or api_key is None:
            raise _attempt_error(
                ErrorCategory.INFRASTRUCTURE,
                "yandex_not_configured",
                "Yandex Search не настроен.",
                retryable=False,
                stage=ExecutionStage.BEFORE_DISPATCH,
            )

        query: dict[str, str] = {
            "searchType": self._settings.search_type,
            "queryText": request.query,
            "page": str(request.page - 1),
        }
        if request.safe_search is not None:
            query["familyMode"] = _SAFE_SEARCH[request.safe_search]
        payload: dict[str, object] = {
            "query": query,
            "groupSpec": {
                "groupMode": "GROUP_MODE_FLAT",
                "groupsOnPage": str(request.limit),
                "docsInGroup": "1",
            },
            "maxPassages": "3",
            "folderId": folder_id,
            "responseFormat": "FORMAT_XML",
        }
        if request.provider_region is not None:
            payload["region"] = request.provider_region
        if request.time_range is not None:
            payload["period"] = _PERIOD[request.time_range]

        response: httpx.Response | None = None
        try:
            async with self._client.stream(
                "POST",
                str(self._settings.endpoint),
                json=payload,
                headers={"Authorization": f"Api-Key {api_key.get_secret_value()}"},
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
                "yandex_connect_failed",
                "Не удалось установить соединение с Yandex Search.",
                retryable=True,
                stage=ExecutionStage.BEFORE_DISPATCH,
            ) from exc
        except httpx.TimeoutException as exc:
            raise _attempt_error(
                ErrorCategory.TIMEOUT,
                "yandex_response_lost",
                "Ответ Yandex Search не получен до истечения срока.",
                retryable=True,
                stage=ExecutionStage.RESPONSE_LOST,
            ) from exc
        except httpx.TransportError as exc:
            raise _attempt_error(
                ErrorCategory.UNKNOWN_OUTCOME,
                "yandex_response_lost",
                "Ответ Yandex Search потерян; итог запроса неизвестен.",
                retryable=True,
                stage=ExecutionStage.RESPONSE_LOST,
            ) from exc

        request_id = _request_id(response.headers) if response is not None else None
        xml = _decode_response(body, self._settings.max_response_bytes, request_id)
        results, warnings = _parse_xml(xml, request.limit, request_id)
        return ProviderSearchResult(
            provider_id=SearchProviderId.YANDEX,
            results=results,
            retrieved_at=context.clock.utc_now(),
            next_page_available=None,
            provider_request_id=request_id,
            warnings=warnings,
        )

    def _validate_request(self, request: ProviderSearchRequest) -> None:
        if request.provider_id is not SearchProviderId.YANDEX:
            raise ValueError("Yandex provider received a request for another provider")
        if len(request.query) > 400:
            raise _unsupported("query")
        if len(request.query.split()) > 40:
            raise _unsupported("query")
        if request.page * request.limit > 250:
            raise _unsupported("page")
        if request.language is not None:
            raise _unsupported("language")
        if request.time_range is SearchTimeRange.YEAR:
            raise _unsupported("time_range")
        if (
            request.provider_region is not None
            and self._settings.search_type not in _REGION_SEARCH_TYPES
        ):
            raise _unsupported("region")
        if (
            request.provider_region is not None
            and re.fullmatch(r"[1-9][0-9]{0,99}", request.provider_region) is None
        ):
            raise _unsupported("region")

    def _timeout(self, context: ExecutionContext) -> float:
        remaining = context.remaining_seconds()
        if remaining is None:
            return self._settings.request_timeout_seconds
        if remaining <= 0:
            raise _attempt_error(
                ErrorCategory.TIMEOUT,
                "search_deadline_exceeded",
                "Срок поисковой операции истёк до отправки запроса.",
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
                "yandex_response_too_large",
                "Ответ Yandex Search превысил допустимый размер.",
                retryable=False,
                stage=ExecutionStage.TERMINAL_KNOWN,
                provider_request_id=_request_id(response.headers),
            )
        body.extend(chunk)
    return bytes(body)


def _decode_response(body: bytes, maximum: int, request_id: str | None) -> bytes:
    try:
        payload = json.loads(body)
        encoded = payload["rawData"]
        if not isinstance(encoded, str):
            raise TypeError
        xml = base64.b64decode(encoded, validate=True)
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _malformed(request_id) from exc
    if len(xml) > maximum:
        raise _attempt_error(
            ErrorCategory.UPSTREAM,
            "yandex_response_too_large",
            "Декодированный ответ Yandex Search превысил допустимый размер.",
            retryable=False,
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )
    return xml


def _parse_xml(
    xml: bytes, limit: int, request_id: str | None
) -> tuple[tuple[SearchResultItem, ...], tuple[Warning, ...]]:
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, ValueError) as exc:
        raise _malformed(request_id) from exc

    error = next((element for element in root.iter() if _local_name(element.tag) == "error"), None)
    if error is not None:
        if error.attrib.get("code") == "15":
            return (), ()
        raise _attempt_error(
            ErrorCategory.UPSTREAM,
            "yandex_search_error",
            "Yandex Search вернул терминальную ошибку поиска.",
            retryable=False,
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )

    parsed: list[SearchResultItem] = []
    skipped = 0
    for doc in (element for element in root.iter() if _local_name(element.tag) == "doc"):
        if len(parsed) >= limit:
            break
        values = {_local_name(child.tag): child for child in doc}
        url = _text(values.get("url"))
        title = _text(values.get("title"))
        if not url or not title or len(url) > 8192 or len(title) > 4096:
            skipped += 1
            continue
        try:
            split = urlsplit(url)
            hostname = split.hostname
        except ValueError:
            skipped += 1
            continue
        if split.scheme not in {"http", "https"} or hostname is None:
            skipped += 1
            continue
        passages = next((child for child in doc if _local_name(child.tag) == "passages"), None)
        snippet_parts = (
            [_text(child) for child in passages if _local_name(child.tag) == "passage"]
            if passages is not None
            else []
        )
        snippet = _clean(" ".join(part for part in snippet_parts if part)) or None
        if snippet is not None:
            snippet = snippet[:8192]
        parsed.append(
            SearchResultItem(
                rank=len(parsed) + 1,
                title=title,
                url=url,
                snippet=snippet,
                host=hostname[:1024],
                published_at=_modtime(_text(values.get("modtime"))),
            )
        )
    warnings: tuple[Warning, ...] = ()
    if skipped:
        warnings = (
            Warning(
                code="malformed_provider_item",
                message="Часть некорректных результатов Yandex Search пропущена.",
                details={"omitted_count": min(skipped, 1000)},
            ),
        )
    return tuple(parsed), warnings


def _text(element: Any | None) -> str:
    if element is None:
        return ""
    return _clean("".join(element.itertext()))


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _local_name(tag: object) -> str:
    value = str(tag)
    return value.rsplit("}", 1)[-1]


def _modtime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _status_error(
    status: int, headers: httpx.Headers, request_id: str | None
) -> ProviderAttemptError:
    if status in {401, 403}:
        return _attempt_error(
            ErrorCategory.UPSTREAM,
            "provider_auth_rejected",
            "Yandex Search отклонил аутентификацию.",
            retryable=False,
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )
    if status == 429:
        return _attempt_error(
            ErrorCategory.RATE_LIMITED,
            "yandex_rate_limited",
            "Yandex Search сообщил об исчерпании лимита запросов.",
            retryable=True,
            retry_after_seconds=_retry_after(headers),
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )
    if status >= 500:
        return _attempt_error(
            ErrorCategory.UPSTREAM,
            "yandex_upstream_error",
            "Yandex Search вернул ошибку upstream-сервиса.",
            retryable=True,
            stage=ExecutionStage.TERMINAL_KNOWN,
            provider_request_id=request_id,
        )
    return _attempt_error(
        ErrorCategory.UPSTREAM,
        "provider_request_rejected",
        "Yandex Search отклонил запрос.",
        retryable=False,
        stage=ExecutionStage.TERMINAL_KNOWN,
        provider_request_id=request_id,
    )


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    return min(int(value), 86400) if value is not None and value.isdecimal() else None


def _request_id(headers: httpx.Headers) -> str | None:
    value = headers.get("x-request-id") or headers.get("x-correlation-id")
    return value[:256] if value else None


def _malformed(request_id: str | None) -> ProviderAttemptError:
    return _attempt_error(
        ErrorCategory.UPSTREAM,
        "yandex_malformed_response",
        "Yandex Search вернул некорректный ответ.",
        retryable=False,
        stage=ExecutionStage.TERMINAL_KNOWN,
        provider_request_id=request_id,
    )


def _unsupported(field: str) -> ProviderAttemptError:
    return _attempt_error(
        ErrorCategory.UNSUPPORTED,
        "yandex_unsupported_option",
        f"Yandex Search не поддерживает параметр {field}.",
        retryable=False,
        stage=ExecutionStage.BEFORE_DISPATCH,
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


def _configuration_revision(settings: YandexSearchSettings) -> str:
    payload: Mapping[str, object] = settings.model_dump(mode="json", exclude={"api_key"})
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
