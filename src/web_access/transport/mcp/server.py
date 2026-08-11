"""FastMCP Streamable HTTP server and v0.2 production tool catalog."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from mcp.types import ToolAnnotations
from pydantic.experimental.missing_sentinel import MISSING

from web_access.application.common.auth import AuthProvider, require_scope
from web_access.application.common.context import CancellationToken, ExecutionContext
from web_access.application.common.errors import AuthorizationError, ErrorCategory, OperationError
from web_access.application.common.results import (
    OperationOutcome,
    OperationResult,
    PublicOperationResult,
    project_result,
)
from web_access.application.search.models import SearchBatchResult
from web_access.core.ids import IdPrefix
from web_access.core.time import Deadline
from web_access.domain.search import SearchProviderSelection
from web_access.transport.mcp.auth import FastMcpAuthAdapter
from web_access.transport.mcp.dependencies import McpRuntimeBinding
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
    "поисковым запросам. Возвращает поисковую выдачу: URL, заголовки, snippets и "
    "metadata поискового backend-а. Не читает содержимое найденных страниц; для "
    "известных URL используйте `web_fetch`, когда эта capability станет доступна. "
    "Некоторые providers (например Yandex) могут расходовать платный provider budget, "
    "поэтому потерянный результат не означает разрешение автоматически повторить "
    "платный запрос."
)


def create_mcp_server(
    auth_provider: AuthProvider,
    runtime: McpRuntimeBinding | None = None,
) -> FastMCP:
    """Create the exact one-tool v0.2 production catalog."""

    binding = runtime or McpRuntimeBinding()
    auth = FastMcpAuthAdapter(auth_provider)
    mcp = FastMCP(
        name="Web Access",
        version="0.2.0",
        instructions=(
            "Web Access v0.2 предоставляет нейтральный к provider поиск страниц и источников. "
            "Результаты поиска — metadata и snippets, а не содержимое найденных страниц."
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

        access_token = get_access_token()
        if access_token is None:
            raise RuntimeError("authenticated token context is missing")
        principal = auth.principal_from_access_token(access_token)
        dependencies = binding.get()
        operation_id = dependencies.ids.new(IdPrefix.OPERATION)
        try:
            require_scope(principal, "search:read")
        except AuthorizationError as error:
            return project_result(
                OperationResult[SearchBatchResult](
                    operation_id=operation_id,
                    outcome=OperationOutcome.REJECTED,
                    error=OperationError(
                        category=ErrorCategory.PERMISSION,
                        code=error.code.value,
                        message=str(error),
                    ),
                )
            )
        context = ExecutionContext(
            operation_id=operation_id,
            principal=principal,
            clock=dependencies.clock,
            cancellation=CancellationToken(),
            deadline=Deadline.after(
                dependencies.clock, dependencies.settings.search.operation_timeout_seconds
            ),
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

    return mcp
