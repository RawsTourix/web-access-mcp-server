"""Normalized safe error projection for FastAPI/Starlette boundaries."""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from web_access.application.common.correlation import correlation_context
from web_access.application.common.errors import (
    AuthorizationError,
    ErrorCategory,
    ErrorEnvelope,
    FieldError,
    OperationError,
)
from web_access.transport.rest.auth import RestAuthenticationError


def _response(
    status_code: int, error: OperationError, *, authenticate: bool = False
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=error).model_dump(mode="json"),
        headers=headers,
    )


async def authentication_error_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RestAuthenticationError):
        return await internal_error_handler(_request, error)
    return _response(
        401,
        OperationError(
            category=ErrorCategory.AUTHENTICATION,
            code=error.code.value,
            message=error.message,
        ),
        authenticate=True,
    )


async def authorization_error_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, AuthorizationError):
        return await internal_error_handler(_request, error)
    status = 403
    return _response(
        status,
        OperationError(
            category=ErrorCategory.PERMISSION,
            code=error.code.value,
            message=str(error),
        ),
    )


async def validation_error_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        return await internal_error_handler(_request, error)
    fields = tuple(
        FieldError(
            path=".".join(str(part) for part in item["loc"]),
            code="invalid_value",
            message="Значение поля не прошло проверку.",
        )
        for item in error.errors()[:32]
    )
    return _response(
        422,
        OperationError(
            category=ErrorCategory.VALIDATION,
            code="invalid_request",
            message="Запрос не прошёл проверку.",
            fields=fields,
        ),
    )


async def internal_error_handler(_request: Request, _error: Exception) -> JSONResponse:
    with correlation_context(
        operation_id=getattr(_request.state, "operation_id", None),
        request_id=getattr(_request.state, "request_id", None),
        trace_id=getattr(_request.state, "trace_id", None),
    ):
        structlog.get_logger(__name__).error(
            "rest_internal_error",
            error_type=type(_error).__name__,
        )
    return _response(
        500,
        OperationError(
            category=ErrorCategory.INTERNAL,
            code="internal_error",
            message="Внутренняя ошибка сервиса.",
        ),
    )
