"""FastAPI operational facade for Service Foundation."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry.trace import format_trace_id
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.middleware.base import RequestResponseEndpoint

from web_access.application.common.auth import require_scope
from web_access.application.common.context import PrincipalContext
from web_access.application.common.errors import AuthorizationError
from web_access.bootstrap.container import RuntimeContainer
from web_access.bootstrap.lifespan import runtime_lifespan
from web_access.core.config import Settings
from web_access.core.ids import IdPrefix
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.infrastructure.observability.context import (
    bind_correlation,
    clear_correlation,
)
from web_access.infrastructure.observability.tracing import operation_span
from web_access.transport.rest.auth import RestAuthAdapter, RestAuthenticationError
from web_access.transport.rest.errors import (
    authentication_error_handler,
    authorization_error_handler,
    internal_error_handler,
    validation_error_handler,
)
from web_access.transport.rest.schemas import LiveResponse, ReadyResponse, StatusResponse

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


def container_from_request(request: Request) -> RuntimeContainer:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, RuntimeContainer):
        raise RuntimeError("runtime container is unavailable")
    return container


async def authenticated_principal(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> PrincipalContext:
    container = container_from_request(request)
    return await RestAuthAdapter(container.auth).authenticate_header(
        request.headers.get("authorization")
    )


async def diagnostic_principal(
    request: Request,
    principal: PrincipalContext = Depends(authenticated_principal),
) -> PrincipalContext:
    require_scope(principal, container_from_request(request).settings.auth.diagnostic_scope)
    return principal


def _request_id(request: Request, container: RuntimeContainer) -> str:
    supplied = request.headers.get("x-request-id")
    if (
        supplied
        and len(supplied) <= container.settings.security.request_id_max_length
        and _REQUEST_ID_PATTERN.fullmatch(supplied)
    ):
        return supplied
    return container.ids.new(IdPrefix.OPERATION).replace("op_", "req_", 1)


def create_rest_app(
    settings: Settings | None = None,
    auth_provider: StaticBearerAuthProvider | None = None,
) -> FastAPI:
    selected_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with runtime_lifespan(selected_settings, auth_provider) as container:
            app.state.container = container
            yield

    app = FastAPI(
        title="Web Access Control Plane",
        version="0.1.0",
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
        container = container_from_request(request)
        operation_id = container.ids.new(IdPrefix.OPERATION)
        request_id = _request_id(request, container)
        clear_correlation()
        bind_correlation(operation_id=operation_id, request_id=request_id)
        method = request.method
        try:
            with operation_span(container.tracer_provider, "http.request") as span:
                if span is not None:
                    trace_id = format_trace_id(span.get_span_context().trace_id)
                    bind_correlation(trace_id=trace_id)
                response = await call_next(request)
        finally:
            clear_correlation()
        route = getattr(request.scope.get("route"), "path", "unmatched")
        status_class = f"{response.status_code // 100}xx"
        container.metrics.requests.labels(
            method=method, route=route, status_class=status_class
        ).inc()
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Operation-ID"] = operation_id
        return response

    @app.get("/health/live", response_model=LiveResponse, tags=["operations"])
    async def health_live(request: Request) -> LiveResponse:
        if not container_from_request(request).health.liveness():
            return LiveResponse()
        return LiveResponse()

    @app.get(
        "/health/ready",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
        tags=["operations"],
    )
    async def health_ready(request: Request) -> ReadyResponse | JSONResponse:
        ready = await container_from_request(request).health.readiness()
        response = ReadyResponse(status="ready" if ready else "unavailable")
        if ready:
            return response
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))

    @app.get("/health/status", response_model=StatusResponse, tags=["operations"])
    async def health_status(
        request: Request,
        _principal: PrincipalContext = Depends(diagnostic_principal),
    ) -> StatusResponse:
        return StatusResponse(service=await container_from_request(request).health.status())

    @app.get("/metrics", include_in_schema=True, tags=["operations"])
    async def metrics(request: Request) -> Response:
        return Response(
            content=container_from_request(request).metrics.render(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app
