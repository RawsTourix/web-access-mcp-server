"""Replaceable authentication port and authorization helpers."""

from __future__ import annotations

from typing import Protocol

from web_access.application.common.context import PrincipalContext
from web_access.application.common.errors import AuthenticationFailure, AuthorizationError


class AuthProvider(Protocol):
    async def authenticate(self, credential: str) -> PrincipalContext | None:
        """Return a trusted principal for a credential, or None."""
        ...


def require_scope(principal: PrincipalContext, required_scope: str) -> None:
    if "*" not in principal.scopes and required_scope not in principal.scopes:
        raise AuthorizationError(
            AuthenticationFailure.INSUFFICIENT_SCOPE,
            "Недостаточно прав для выполнения операции.",
        )


def require_owner(principal: PrincipalContext, owner_principal_id: str) -> None:
    if principal.principal_id != owner_principal_id:
        raise AuthorizationError(
            AuthenticationFailure.OWNER_ACCESS_DENIED,
            "Ресурс принадлежит другому принципалу.",
        )
