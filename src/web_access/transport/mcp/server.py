"""FastMCP Streamable HTTP server and exact v0.3 production tool catalog."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from mcp.types import ToolAnnotations
from pydantic.experimental.missing_sentinel import MISSING

from web_access.application.common.auth import AuthProvider, require_scope
from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.errors import AuthorizationError, ErrorCategory, OperationError
from web_access.application.common.results import (
    BatchItemResult,
    LeafOutcome,
    OperationOutcome,
    OperationResult,
    PublicOperationResult,
    aggregate_batch_outcome,
    project_result,
)
from web_access.application.content.models import (
    ContentNativeParseBatchResult,
    ContentReadResult,
)
from web_access.application.content.service import (
    ContentCursorError,
    ContentNotFoundError,
    ContentUnavailableError,
)
from web_access.application.retrieval.models import RetrievalBatchResult
from web_access.application.search.models import SearchBatchResult
from web_access.core.ids import IdPrefix
from web_access.core.time import Deadline
from web_access.domain.search import SearchProviderSelection
from web_access.transport.mcp.auth import FastMcpAuthAdapter
from web_access.transport.mcp.content_schemas import (
    ContentGetInput,
    ContentParseInput,
    ContentReadBatchResult,
    McpContentIds,
    McpContentReadItems,
    McpMaxChars,
    McpUrls,
    WebFetchInput,
)
from web_access.transport.mcp.dependencies import McpDependencies, McpRuntimeBinding
from web_access.transport.mcp.search_schemas import (
    McpLanguage,
    McpLimit,
    McpPage,
    McpProvider,
    McpQueries,
    McpRegion,
    McpSafeSearch,
    McpTimeRange,
    WebSearchInput,
)

_WEB_SEARCH_DESCRIPTION = (
    "Ищет страницы и источники в интернете по одному или нескольким независимым "
    "поисковым запросам. Возвращает URL, заголовки, snippets и metadata поискового "
    "backend-а, но не читает содержимое найденных страниц. Для известного URL "
    "используйте `web_fetch`. Некоторые providers, например Yandex, могут расходовать "
    "платный budget, поэтому потерянный результат нельзя автоматически повторять."
)
_WEB_FETCH_DESCRIPTION = (
    "Немедленно получает один или несколько известных HTTP(S)-ресурсов через безопасный "
    "Retrieval. Сохраняет raw ContentObject, выполняет L0 Inspection и доступный L1 Native "
    "Parsing. Не запускает Browser, OCR/L2 или durable Job. Вызов создаёт Content resources, "
    "поэтому потерянный результат нельзя слепо повторять."
)
_CONTENT_GET_DESCRIPTION = (
    "Читает уже существующие ContentObjects без повторного HTTP-запроса или браузинга. "
    "Для текста возвращает ограниченный UTF-8 chunk и opaque cursor; для бинарного объекта "
    "возвращает metadata и доступные representations без скрытой конвертации."
)
_CONTENT_PARSE_DESCRIPTION = (
    "Немедленно запускает зарегистрированный L1 Native Parser для существующих ContentObjects. "
    "Использует detected format и canonical parser registry, не принимает имя библиотеки, не "
    "запускает OCR/L2 и не создаёт durable Job. Совместимое representation переиспользуется."
)


def create_mcp_server(
    auth_provider: AuthProvider,
    runtime: McpRuntimeBinding | None = None,
) -> FastMCP:
    """Create the exact four-tool v0.3 production catalog."""

    binding = runtime or McpRuntimeBinding()
    auth = FastMcpAuthAdapter(auth_provider)
    mcp = FastMCP(
        name="Web Access",
        version="0.3.0",
        instructions=(
            "Production-каталог Web Access v0.3 предоставляет Search, Retrieval и Content: "
            "ищет URL, безопасно получает известные HTTP(S)-ресурсы, читает сохранённые "
            "ContentObjects и запускает их L1 Native Parsing. Browser и Durable Jobs в этом "
            "каталоге отсутствуют."
        ),
        auth=auth,
        mask_error_details=True,
        strict_input_validation=True,
    )

    @mcp.tool(
        name="web_search",
        description=_WEB_SEARCH_DESCRIPTION,
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def web_search(
        queries: McpQueries,
        provider: McpProvider = SearchProviderSelection.DEFAULT,
        page: McpPage = 1,
        limit: McpLimit = 10,
        language: McpLanguage = MISSING,
        region: McpRegion = MISSING,
        safe_search: McpSafeSearch = MISSING,
        time_range: McpTimeRange = MISSING,
    ) -> PublicOperationResult[SearchBatchResult]:
        """Execute provider-neutral Search through the shared application service."""

        dependencies, principal, operation_id = _mcp_call(auth, binding)
        denied = _authorize(operation_id, principal, "search:read")
        if denied is not None:
            return denied
        context = _context(
            dependencies,
            principal,
            operation_id,
            dependencies.settings.search.operation_timeout_seconds,
        )
        payload = WebSearchInput(
            queries=queries,
            provider=provider,
            page=page,
            limit=limit,
            language=language,
            region=region,
            safe_search=safe_search,
            time_range=time_range,
        )
        return project_result(await dependencies.search.search(context, payload.to_application()))

    @mcp.tool(
        name="web_fetch",
        description=_WEB_FETCH_DESCRIPTION,
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def web_fetch(urls: McpUrls) -> PublicOperationResult[RetrievalBatchResult]:
        """Run the fixed safe Retrieval -> raw -> L0 -> available L1 pipeline."""

        dependencies, principal, operation_id = _mcp_call(auth, binding)
        denied = _authorize(operation_id, principal, "retrieval:read")
        if denied is not None:
            return denied
        context = _context(
            dependencies,
            principal,
            operation_id,
            dependencies.settings.retrieval.operation_timeout_seconds,
        )
        payload = WebFetchInput(urls=urls)
        return project_result(await dependencies.retrieval.fetch(context, payload.to_application()))

    @mcp.tool(
        name="content_get",
        description=_CONTENT_GET_DESCRIPTION,
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def content_get(
        items: McpContentReadItems,
        max_chars: McpMaxChars = 12000,
    ) -> PublicOperationResult[ContentReadBatchResult]:
        """Read bounded chunks from existing authorized ContentObjects."""

        dependencies, principal, operation_id = _mcp_call(auth, binding)
        denied = _authorize(operation_id, principal, "content:read")
        if denied is not None:
            return denied
        payload = ContentGetInput(items=items, max_chars=max_chars)
        context = _context(dependencies, principal, operation_id)
        results: list[BatchItemResult[ContentReadResult]] = []
        for index, item in enumerate(payload.items):
            cursor = None if item.cursor is MISSING else item.cursor
            try:
                data = await dependencies.content.read(
                    context,
                    item.content_id,
                    max_chars=payload.max_chars,
                    cursor=cursor,
                )
                results.append(
                    BatchItemResult(index=index, outcome=LeafOutcome.SUCCEEDED, data=data)
                )
            except Exception as error:
                results.append(_content_error(index, error))
        return project_result(_content_read_result(operation_id, results))

    @mcp.tool(
        name="content_parse",
        description=_CONTENT_PARSE_DESCRIPTION,
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def content_parse(
        content_ids: McpContentIds,
    ) -> PublicOperationResult[ContentNativeParseBatchResult]:
        """Run canonical request-bound L1 parsing with representation reuse."""

        dependencies, principal, operation_id = _mcp_call(auth, binding)
        for scope in ("content:read", "content:write"):
            denied = _authorize(operation_id, principal, scope)
            if denied is not None:
                return denied
        payload = ContentParseInput(content_ids=content_ids)
        context = _context(dependencies, principal, operation_id)
        return project_result(
            await dependencies.content.native_parse_many(context, payload.content_ids)
        )

    return mcp


def _mcp_call(
    auth: FastMcpAuthAdapter, binding: McpRuntimeBinding
) -> tuple[McpDependencies, PrincipalContext, str]:
    access_token = get_access_token()
    if access_token is None:
        raise RuntimeError("authenticated token context is missing")
    principal = auth.principal_from_access_token(access_token)
    dependencies = binding.get()
    return dependencies, principal, dependencies.ids.new(IdPrefix.OPERATION)


def _context(
    dependencies: McpDependencies,
    principal: PrincipalContext,
    operation_id: str,
    timeout_seconds: float | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        operation_id=operation_id,
        principal=principal,
        clock=dependencies.clock,
        cancellation=CancellationToken(),
        deadline=(
            Deadline.after(dependencies.clock, timeout_seconds)
            if timeout_seconds is not None
            else None
        ),
    )


def _authorize(
    operation_id: str, principal: PrincipalContext, scope: str
) -> PublicOperationResult | None:
    try:
        require_scope(principal, scope)
    except AuthorizationError as error:
        return project_result(
            OperationResult(
                operation_id=operation_id,
                outcome=OperationOutcome.REJECTED,
                error=OperationError(
                    category=ErrorCategory.PERMISSION,
                    code=error.code.value,
                    message=str(error),
                ),
            )
        )
    return None


def _content_error(index: int, error: Exception) -> BatchItemResult[ContentReadResult]:
    if isinstance(error, AuthorizationError):
        category, code, outcome, message = (
            ErrorCategory.PERMISSION,
            error.code.value,
            LeafOutcome.REJECTED,
            str(error),
        )
    elif isinstance(error, ContentNotFoundError):
        category, code, outcome, message = (
            ErrorCategory.NOT_FOUND,
            error.code,
            LeafOutcome.FAILED,
            "Content не найден.",
        )
    elif isinstance(error, ContentUnavailableError):
        category, code, outcome, message = (
            ErrorCategory.CONFLICT,
            error.code,
            LeafOutcome.FAILED,
            "Content недоступен.",
        )
    elif isinstance(error, ContentCursorError):
        category, code, outcome, message = (
            ErrorCategory.VALIDATION,
            error.code,
            LeafOutcome.FAILED,
            "Cursor недействителен или не соответствует Content.",
        )
    else:
        category, code, outcome, message = (
            ErrorCategory.INTERNAL,
            getattr(error, "code", "content_processing_failed"),
            LeafOutcome.FAILED,
            "Не удалось прочитать Content.",
        )
    return BatchItemResult(
        index=index,
        outcome=outcome,
        error=OperationError(category=category, code=code, message=message),
    )


def _content_read_result(
    operation_id: str,
    items: list[BatchItemResult[ContentReadResult]],
) -> OperationResult[ContentReadBatchResult]:
    outcome = aggregate_batch_outcome([item.outcome for item in items])
    error = None
    if outcome not in {OperationOutcome.SUCCEEDED, OperationOutcome.PARTIAL_SUCCESS}:
        error = next(item.error for item in items if item.error is not None)
    return OperationResult(
        operation_id=operation_id,
        outcome=outcome,
        data=ContentReadBatchResult(items=tuple(items)),
        error=error,
    )
