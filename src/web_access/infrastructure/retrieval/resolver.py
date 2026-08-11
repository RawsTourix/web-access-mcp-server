"""aiohttp resolver that returns only the addresses it has validated."""

from __future__ import annotations

import socket
from typing import Protocol

from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver


class AddressPolicy(Protocol):
    def validate_addresses(self, addresses: tuple[str, ...]) -> tuple[object, ...]: ...


class ValidatingResolver(AbstractResolver):
    """Validate the complete DNS answer before aiohttp selects a connect address."""

    def __init__(
        self,
        policy: AddressPolicy,
        underlying: AbstractResolver | None = None,
    ) -> None:
        self._policy = policy
        self._underlying = underlying or DefaultResolver()
        self._closed = False

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        if self._closed:
            raise RuntimeError("Retrieval resolver is closed")
        records = await self._underlying.resolve(host, port, family)
        self._policy.validate_addresses(tuple(record["host"] for record in records))
        return records

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._underlying.close()
