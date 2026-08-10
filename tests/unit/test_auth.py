from __future__ import annotations

import json
import logging

import pytest
from pydantic import SecretStr

from web_access.application.common.auth import require_owner, require_scope
from web_access.application.common.errors import AuthorizationError
from web_access.core.config import PrincipalSettings
from web_access.infrastructure.auth import static_bearer
from web_access.infrastructure.auth.static_bearer import StaticBearerAuthProvider
from web_access.transport.mcp.auth import FastMcpAuthAdapter
from web_access.transport.rest.auth import RestAuthAdapter, RestAuthenticationError

TOKEN_A1 = "a" * 32
TOKEN_A2 = "b" * 32
TOKEN_B = "c" * 32


def _principals() -> tuple[PrincipalSettings, ...]:
    return (
        PrincipalSettings(
            principal_id="agent-a",
            tokens=(SecretStr(TOKEN_A1), SecretStr(TOKEN_A2)),
            scopes=frozenset({"content:read", "admin:read"}),
        ),
        PrincipalSettings(
            principal_id="agent-b",
            tokens=(SecretStr(TOKEN_B),),
            scopes=frozenset({"*"}),
        ),
    )


@pytest.mark.asyncio
async def test_valid_invalid_missing_and_rotation_authentication() -> None:
    provider = StaticBearerAuthProvider(_principals())
    rest = RestAuthAdapter(provider)
    with pytest.raises(RestAuthenticationError) as missing:
        await rest.authenticate_header(None)
    assert missing.value.code.value == "missing_credentials"
    with pytest.raises(RestAuthenticationError) as invalid:
        await rest.authenticate_header("Bearer invalid-credential")
    assert invalid.value.code.value == "invalid_credentials"
    first = await rest.authenticate_header(f"Bearer {TOKEN_A1}")
    second = await rest.authenticate_header(f"bearer {TOKEN_A2}")
    other = await rest.authenticate_header(f"Bearer {TOKEN_B}")
    assert first == second
    assert first.principal_id == "agent-a"
    assert other.principal_id == "agent-b"


@pytest.mark.asyncio
async def test_comparison_walks_complete_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    original = static_bearer.secrets.compare_digest

    def recording_compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(static_bearer.secrets, "compare_digest", recording_compare)
    provider = StaticBearerAuthProvider(_principals())
    principal = await provider.authenticate(TOKEN_A1)
    assert principal is not None
    assert principal.principal_id == "agent-a"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_scope_wildcard_and_owner_isolation() -> None:
    provider = StaticBearerAuthProvider(_principals())
    first = await provider.authenticate(TOKEN_A1)
    wildcard = await provider.authenticate(TOKEN_B)
    assert first is not None
    assert wildcard is not None
    require_scope(first, "content:read")
    require_scope(wildcard, "any:new:scope")
    require_owner(first, "agent-a")
    with pytest.raises(AuthorizationError):
        require_scope(first, "admin:write")
    with pytest.raises(AuthorizationError):
        require_owner(first, "client-supplied-owner")


@pytest.mark.asyncio
async def test_rest_and_mcp_have_identical_principal_context() -> None:
    provider = StaticBearerAuthProvider(_principals())
    rest_principal = await RestAuthAdapter(provider).authenticate_header(f"Bearer {TOKEN_A1}")
    access_token = await FastMcpAuthAdapter(provider).verify_token(TOKEN_A1)
    assert access_token is not None
    mcp_principal = FastMcpAuthAdapter.principal_from_access_token(access_token)
    assert mcp_principal == rest_principal


@pytest.mark.asyncio
async def test_tokens_do_not_leak_to_logs_or_repr(caplog: pytest.LogCaptureFixture) -> None:
    provider = StaticBearerAuthProvider(_principals())
    caplog.set_level(logging.DEBUG)
    await provider.authenticate(TOKEN_A1)
    rendered = json.dumps([record.getMessage() for record in caplog.records])
    assert TOKEN_A1 not in rendered
    assert TOKEN_A1 not in repr(_principals())
