"""REST Bearer header parsing backed by the shared AuthProvider."""

from __future__ import annotations

from dataclasses import dataclass

from web_access.application.common.auth import AuthProvider
from web_access.application.common.context import PrincipalContext
from web_access.application.common.errors import AuthenticationFailure


@dataclass(frozen=True, slots=True)
class RestAuthenticationError(Exception):
    code: AuthenticationFailure
    message: str


class RestAuthAdapter:
    def __init__(self, provider: AuthProvider) -> None:
        self._provider = provider

    async def authenticate_header(self, authorization: str | None) -> PrincipalContext:
        if authorization is None:
            raise RestAuthenticationError(
                AuthenticationFailure.MISSING_CREDENTIALS,
                "Требуется Bearer-аутентификация.",
            )
        scheme, separator, credential = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not credential.strip():
            raise RestAuthenticationError(
                AuthenticationFailure.INVALID_CREDENTIALS,
                "Недействительные учётные данные.",
            )
        principal = await self._provider.authenticate(credential.strip())
        if principal is None:
            raise RestAuthenticationError(
                AuthenticationFailure.INVALID_CREDENTIALS,
                "Недействительные учётные данные.",
            )
        return principal
