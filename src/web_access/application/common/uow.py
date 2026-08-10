"""Application-owned transaction boundary contract."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self


class UnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None:
        """Explicitly commit the current unit of work."""
        ...

    async def rollback(self) -> None:
        """Explicitly roll back the current unit of work."""
        ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
