"""FastAPI operational facade for Service Foundation."""

from __future__ import annotations

import re
from time import monotonic

from fastapi import Depends, FastAPI, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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
from web_access.application.common.errors import AuthorizationError
from web_access.application.common.results import PublicOperationResult, project_result
from web_access.application.search.models import SearchBatchResult
from web_access.application.search.readiness import SearchProviderDiscovery
from web_access.core.ids import IdPrefix
from web_access.transport.rest.auth import RestAuthAdapter, RestAuthenticationError
from web_access.transport.rest.dependencies import RestDependencies, dependencies_from_request
from web_access.transport.rest.errors import (
    authentication_error_handler,
    authorization_error_handler,
    internal_error_handler,
    validation_error_handler,
)
from web_access.transport.rest.schemas import LiveResponse, ReadyResponse, StatusResponse
from web_access.transport.rest.search_schemas import RestSearchRequest

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


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


def _execution_context(
    request: Request,
    dependencies: RestDependencies,
    principal: PrincipalContext,
) -> ExecutionContext:
    return ExecutionContext(
        operation_id=request.state.operation_id,
        principal=principal,
        clock=dependencies.clock,
        cancellation=CancellationToken(),
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
        version="0.2.0",
        lifespan=lifespan,
    )
    app.add_exception_handler(RestAuthenticationError, authentication_error_handler)
    app.add_exception_handler(AuthorizationError, authorization_error_handler)
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
        principal: PrincipalContext = Depends(search_principal),
    ) -> PublicOperationResult[SearchBatchResult]:
        dependencies = dependencies_from_request(request)
        result = await dependencies.search.search(
            _execution_context(request, dependencies, principal),
            payload.to_application(),
        )
        return project_result(result)

    @app.get(
        "/api/v1/search/providers",
        response_model=tuple[SearchProviderDiscovery, ...],
        tags=["search"],
    )
    async def search_providers(
        request: Request,
        _principal: PrincipalContext = Depends(search_principal),
    ) -> tuple[SearchProviderDiscovery, ...]:
        return await dependencies_from_request(request).search_readiness.providers()

    return app
