"""FastAPI operational facade for Service Foundation."""

from __future__ import annotations

import re
from time import monotonic

from fastapi import Depends, FastAPI, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Lifespan

from web_access.application.common.auth import require_scope
from web_access.application.common.context import PrincipalContext
from web_access.application.common.correlation import bind_correlation, clear_correlation
from web_access.application.common.errors import AuthorizationError
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
        dependencies = dependencies_from_request(request)
        operation_id = dependencies.ids.new(IdPrefix.OPERATION)
        request_id = _request_id(request, dependencies)
        clear_correlation()
        bind_correlation(operation_id=operation_id, request_id=request_id)
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

    return app
