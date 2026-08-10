"""FastMCP 3.4 token verifier delegating to the common AuthProvider."""

from __future__ import annotations

from fastmcp.server.auth import AccessToken, TokenVerifier

from web_access.application.common.auth import AuthProvider
from web_access.application.common.context import PrincipalContext


class FastMcpAuthAdapter(TokenVerifier):
    """Transport-only verifier over the same registry used by REST."""

    def __init__(self, provider: AuthProvider) -> None:
        super().__init__()
        self._provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await self._provider.authenticate(token)
        if principal is None:
            return None
        return AccessToken(
            token=token,
            client_id=principal.principal_id,
            scopes=sorted(principal.scopes),
            claims={
                "principal_type": principal.principal_type.value,
                "registry_revision": principal.registry_revision,
            },
        )

    @staticmethod
    def principal_from_access_token(token: AccessToken) -> PrincipalContext:
        return PrincipalContext(
            principal_id=token.client_id,
            scopes=frozenset(token.scopes),
            registry_revision=(
                str(token.claims["registry_revision"])
                if token.claims and token.claims.get("registry_revision") is not None
                else None
            ),
        )
