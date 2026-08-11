"""FastAPI operational facade for Service Foundation."""

from __future__ import annotations

import re
from time import monotonic
from typing import Annotated

from fastapi import Depends, FastAPI, Path, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry.trace import get_current_span
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Lifespan

from web_access.application.common.auth import require_scope
from web_access.application.common.context import (
    CancellationToken,
    ExecutionContext,
    PrincipalContext,
)
from web_access.application.common.correlation import bind_correlation, clear_correlation
from web_access.application.common.errors import AuthorizationError, ErrorCategory
from web_access.application.common.results import (
    PublicOperationOutcome,
    PublicOperationResult,
    project_result,
)
from web_access.application.content.models import (
    ContentInspectBatchResult,
    ContentMetadata,
    ContentNativeParseBatchResult,
    ContentRepresentationsResult,
)
from web_access.application.content.service import ContentLifecycleError
from web_access.application.retrieval.models import RetrievalBatchResult
from web_access.application.search.models import SearchBatchResult
from web_access.application.search.readiness import SearchProvidersData
from web_access.core.ids import IdPrefix
from web_access.core.time import Deadline
from web_access.transport.rest.auth import RestAuthAdapter, RestAuthenticationError
from web_access.transport.rest.content_schemas import RestContentIdsRequest, RestNativeParseRequest
from web_access.transport.rest.dependencies import RestDependencies, dependencies_from_request
from web_access.transport.rest.errors import (
    authentication_error_handler,
    authorization_error_handler,
    content_error_handler,
    internal_error_handler,
    validation_error_handler,
)
from web_access.transport.rest.retrieval_schemas import RestFetchRequest
from web_access.transport.rest.schemas import LiveResponse, ReadyResponse, StatusResponse
from web_access.transport.rest.search_schemas import RestSearchRequest

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
ContentPathId = Annotated[str, Path(min_length=1, max_length=128)]


async def authenticated_principal(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> PrincipalContext:
    dependencies = dependencies_from_request(request)
    return await RestAuthAdapter(dependencies.auth).authenticate_header(
        request.headers.get("authorization")
    )


async def diagnostic_principal(
    request: Request,
    principal: PrincipalContext = Depends(authenticated_principal),
) -> PrincipalContext:
    require_scope(principal, dependencies_from_request(request).settings.auth.diagnostic_scope)
    return principal


async def search_principal(
    principal: PrincipalContext = Depends(authenticated_principal),
) -> PrincipalContext:
    require_scope(principal, "search:read")
    return principal


async def retrieval_principal(
    principal: PrincipalContext = Depends(authenticated_principal),
) -> PrincipalContext:
    require_scope(principal, "retrieval:read")
    return principal


async def content_read_principal(
    principal: PrincipalContext = Depends(authenticated_principal),
) -> PrincipalContext:
    require_scope(principal, "content:read")
    return principal


async def content_parse_principal(
    principal: PrincipalContext = Depends(content_read_principal),
) -> PrincipalContext:
    require_scope(principal, "content:write")
    return principal


def _execution_context(
    request: Request,
    dependencies: RestDependencies,
    principal: PrincipalContext,
    *,
    timeout_seconds: float | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        operation_id=request.state.operation_id,
        principal=principal,
        clock=dependencies.clock,
        cancellation=CancellationToken(),
        deadline=Deadline.after(
            dependencies.clock,
            timeout_seconds or dependencies.settings.search.operation_timeout_seconds,
        ),
        request_id=request.state.request_id,
        trace_id=request.state.trace_id,
    )


def _request_id(request: Request, dependencies: RestDependencies) -> str:
    supplied = request.headers.get("x-request-id")
    if (
        supplied
        and len(supplied) <= dependencies.settings.security.request_id_max_length
        and _REQUEST_ID_PATTERN.fullmatch(supplied)
    ):
        return supplied
    return dependencies.ids.new(IdPrefix.OPERATION).replace("op_", "req_", 1)


def create_rest_app(lifespan: Lifespan[FastAPI]) -> FastAPI:
    app = FastAPI(
        title="Web Access Control Plane",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_exception_handler(RestAuthenticationError, authentication_error_handler)
    app.add_exception_handler(AuthorizationError, authorization_error_handler)
    app.add_exception_handler(ContentLifecycleError, content_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)

    @app.middleware("http")
    async def correlation_and_metrics(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        dependencies = dependencies_from_request(request)
        operation_id = dependencies.ids.new(IdPrefix.OPERATION)
        request_id = _request_id(request, dependencies)
        span_context = get_current_span().get_span_context()
        trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else None
        request.state.operation_id = operation_id
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        clear_correlation()
        bind_correlation(operation_id=operation_id, request_id=request_id, trace_id=trace_id)
        started = monotonic()
        try:
            response = await call_next(request)
        finally:
            clear_correlation()
        route = getattr(request.scope.get("route"), "path", "unmatched")
        dependencies.metrics.observe_http_request(
            method=request.method,
            route=route,
            status_class=f"{response.status_code // 100}xx",
            duration_seconds=monotonic() - started,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Operation-ID"] = operation_id
        return response

    @app.get("/health/live", response_model=LiveResponse, tags=["operations"])
    async def health_live(request: Request) -> LiveResponse:
        _ = dependencies_from_request(request).health.liveness()
        return LiveResponse()

    @app.get(
        "/health/ready",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
        tags=["operations"],
    )
    async def health_ready(request: Request) -> ReadyResponse | JSONResponse:
        dependencies = dependencies_from_request(request)
        ready = await dependencies.health.readiness()
        dependencies.metrics.set_readiness(ready)
        response = ReadyResponse(status="ready" if ready else "unavailable")
        if ready:
            return response
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))

    @app.get("/health/status", response_model=StatusResponse, tags=["operations"])
    async def health_status(
        request: Request,
        _principal: PrincipalContext = Depends(diagnostic_principal),
    ) -> StatusResponse:
        return StatusResponse(service=await dependencies_from_request(request).health.status())

    @app.get("/metrics", include_in_schema=True, tags=["operations"])
    async def metrics(request: Request) -> Response:
        return Response(
            content=dependencies_from_request(request).metrics.render(),
            media_type=CONTENT_TYPE_LATEST,
        )

    @app.post(
        "/api/v1/search",
        response_model=PublicOperationResult[SearchBatchResult],
        tags=["search"],
    )
    async def search(
        payload: RestSearchRequest,
        request: Request,
        response: Response,
        principal: PrincipalContext = Depends(search_principal),
    ) -> PublicOperationResult[SearchBatchResult]:
        dependencies = dependencies_from_request(request)
        result = await dependencies.search.search(
            _execution_context(request, dependencies, principal),
            payload.to_application(),
        )
        response.status_code = _search_status(result.error.category if result.error else None)
        return project_result(result)

    @app.get(
        "/api/v1/search/providers",
        response_model=PublicOperationResult[SearchProvidersData],
        tags=["search"],
    )
    async def search_providers(
        request: Request,
        principal: PrincipalContext = Depends(search_principal),
    ) -> PublicOperationResult[SearchProvidersData]:
        dependencies = dependencies_from_request(request)
        result = await dependencies.search_readiness.discover(
            _execution_context(request, dependencies, principal)
        )
        return project_result(result)

    @app.post(
        "/api/v1/retrieval/fetch",
        response_model=PublicOperationResult[RetrievalBatchResult],
        tags=["retrieval"],
    )
    async def retrieval_fetch(
        payload: RestFetchRequest,
        request: Request,
        response: Response,
        principal: PrincipalContext = Depends(retrieval_principal),
    ) -> PublicOperationResult[RetrievalBatchResult]:
        dependencies = dependencies_from_request(request)
        result = await dependencies.retrieval.fetch(
            _execution_context(
                request,
                dependencies,
                principal,
                timeout_seconds=dependencies.settings.retrieval.operation_timeout_seconds,
            ),
            payload.to_application(),
        )
        response.status_code = _operation_status(result.error.category if result.error else None)
        return project_result(result)

    @app.get(
        "/api/v1/content/{content_id}",
        response_model=PublicOperationResult[ContentMetadata],
        tags=["content"],
    )
    async def content_metadata(
        content_id: ContentPathId,
        request: Request,
        principal: PrincipalContext = Depends(content_read_principal),
    ) -> PublicOperationResult[ContentMetadata]:
        dependencies = dependencies_from_request(request)
        data = await dependencies.content.metadata(
            _execution_context(request, dependencies, principal), content_id
        )
        return _success(request.state.operation_id, data)

    @app.get(
        "/api/v1/content/{content_id}/representations",
        response_model=PublicOperationResult[ContentRepresentationsResult],
        tags=["content"],
    )
    async def content_representations(
        content_id: ContentPathId,
        request: Request,
        principal: PrincipalContext = Depends(content_read_principal),
    ) -> PublicOperationResult[ContentRepresentationsResult]:
        dependencies = dependencies_from_request(request)
        data = await dependencies.content.representations(
            _execution_context(request, dependencies, principal), content_id
        )
        return _success(request.state.operation_id, data)

    @app.get("/api/v1/content/{content_id}/data", tags=["content"])
    async def content_data(
        content_id: ContentPathId,
        request: Request,
        principal: PrincipalContext = Depends(content_read_principal),
    ) -> Response:
        dependencies = dependencies_from_request(request)
        authorized = await dependencies.content.open_data(
            _execution_context(request, dependencies, principal), content_id
        )
        if request.headers.get("range") is not None:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{authorized.content.size_bytes}"},
            )
        media_type = _safe_download_media_type(authorized.content.media_type)
        headers = {
            "Content-Length": str(authorized.content.size_bytes),
            "Content-Disposition": _content_disposition(authorized.source_filename),
            "X-Content-Type-Options": "nosniff",
        }
        return StreamingResponse(authorized.stream, media_type=media_type, headers=headers)

    @app.post(
        "/api/v1/content/inspect",
        response_model=PublicOperationResult[ContentInspectBatchResult],
        tags=["content"],
    )
    async def content_inspect(
        payload: RestContentIdsRequest,
        request: Request,
        response: Response,
        principal: PrincipalContext = Depends(content_read_principal),
    ) -> PublicOperationResult[ContentInspectBatchResult]:
        dependencies = dependencies_from_request(request)
        result = await dependencies.content.inspect_many(
            _execution_context(request, dependencies, principal), payload.content_ids
        )
        response.status_code = _operation_status(result.error.category if result.error else None)
        return project_result(result)

    @app.post(
        "/api/v1/content/native-parse",
        response_model=PublicOperationResult[ContentNativeParseBatchResult],
        tags=["content"],
    )
    async def content_native_parse(
        payload: RestNativeParseRequest,
        request: Request,
        response: Response,
        principal: PrincipalContext = Depends(content_parse_principal),
    ) -> PublicOperationResult[ContentNativeParseBatchResult]:
        _ = payload.reuse_existing
        dependencies = dependencies_from_request(request)
        result = await dependencies.content.native_parse_many(
            _execution_context(request, dependencies, principal), payload.content_ids
        )
        response.status_code = _operation_status(result.error.category if result.error else None)
        return project_result(result)

    return app


def _search_status(category: ErrorCategory | None) -> int:
    return _operation_status(category)


def _operation_status(category: ErrorCategory | None) -> int:
    if category is None:
        return 200
    return {
        ErrorCategory.VALIDATION: 422,
        ErrorCategory.UNSUPPORTED: 422,
        ErrorCategory.AUTHENTICATION: 401,
        ErrorCategory.PERMISSION: 403,
        ErrorCategory.POLICY: 403,
        ErrorCategory.NOT_FOUND: 404,
        ErrorCategory.CONFLICT: 409,
        ErrorCategory.RATE_LIMITED: 429,
        ErrorCategory.UPSTREAM: 502,
        ErrorCategory.CAPACITY: 503,
        ErrorCategory.INFRASTRUCTURE: 503,
        ErrorCategory.TIMEOUT: 504,
        ErrorCategory.UNKNOWN_OUTCOME: 502,
    }.get(category, 500)


def _success(operation_id: str, data: object) -> PublicOperationResult:
    return PublicOperationResult(
        operation_id=operation_id,
        outcome=PublicOperationOutcome.SUCCEEDED,
        data=data,
    )


def _safe_download_media_type(media_type: str | None) -> str:
    if media_type is None:
        return "application/octet-stream"
    normalized = media_type.split(";", 1)[0].strip().lower()
    if normalized in {"text/html", "image/svg+xml"}:
        return "application/octet-stream"
    if re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", normalized):
        return normalized
    return "application/octet-stream"


def _content_disposition(filename: str | None) -> str:
    selected = filename or "content.bin"
    safe = "".join(
        "_" if character in {'"', "/", "\\"} or ord(character) < 32 else character
        for character in selected
    ).strip(" .")[:150]
    return f'attachment; filename="{safe or "content.bin"}"'
