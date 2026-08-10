"""Static bearer AuthProvider baseline with rotation overlap support."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from web_access.application.common.context import PrincipalContext
from web_access.core.config import PrincipalSettings


@dataclass(frozen=True, slots=True)
class _Credential:
    principal: PrincipalContext
    secret: str = field(repr=False)


class StaticBearerAuthProvider:
    """Authenticate configured service credentials without leaking match details."""

    def __init__(self, principals: tuple[PrincipalSettings, ...]) -> None:
        if not principals:
            raise ValueError("static bearer provider requires at least one principal")
        self._credentials = tuple(
            _Credential(
                principal=PrincipalContext(
                    principal_id=principal.principal_id,
                    scopes=principal.scopes,
                    registry_revision="static-v1",
                ),
                secret=token.get_secret_value(),
            )
            for principal in principals
            for token in principal.tokens
        )

    async def authenticate(self, credential: str) -> PrincipalContext | None:
        matched: PrincipalContext | None = None
        # Compare against the complete registry. Config validation guarantees one match at most.
        for configured in self._credentials:
            if secrets.compare_digest(credential, configured.secret):
                matched = configured.principal
        return matched
