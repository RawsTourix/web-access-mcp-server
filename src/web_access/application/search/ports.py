"""Application-owned Search provider, cache, admission, and usage ports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from web_access.application.common.context import ExecutionContext
from web_access.application.common.errors import OperationError
from web_access.application.common.results import ExecutionStage
from web_access.application.search.models import (
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResult,
    SearchQueryData,
)
from web_access.domain.search import SearchProviderId


class SearchProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    async def search(
        self, context: ExecutionContext, request: ProviderSearchRequest
    ) -> ProviderSearchResult:
        """Execute exactly one observable upstream request attempt."""
        ...


class CacheLookupState(StrEnum):
    HIT = "hit"
    MISS = "miss"
    CORRUPT = "corrupt"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CacheLookup:
    state: CacheLookupState
    value: SearchQueryData | None = None


class SearchCache(Protocol):
    async def get(self, identity: str) -> CacheLookup: ...

    async def put(self, identity: str, value: SearchQueryData, ttl_seconds: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class SingleFlightLease:
    identity: str
    holder: bool
    token: str | None = None


class SearchSingleFlight(Protocol):
    async def acquire(self, identity: str, *, wait_seconds: float | None) -> SingleFlightLease: ...

    async def release(self, lease: SingleFlightLease) -> None: ...


@dataclass(frozen=True, slots=True)
class RateAdmission:
    allowed: bool
    retry_after_seconds: float | None = None


class ProviderRateLimiter(Protocol):
    async def admit(
        self,
        *,
        principal_id: str,
        provider_id: SearchProviderId,
        wait_seconds: float | None,
    ) -> RateAdmission: ...


@dataclass(frozen=True, slots=True)
class ConcurrencyLease:
    provider_id: SearchProviderId
    token: str


class ProviderConcurrencyLimiter(Protocol):
    async def acquire(
        self, provider_id: SearchProviderId, *, wait_seconds: float | None
    ) -> ConcurrencyLease | None: ...

    async def release(self, lease: ConcurrencyLease) -> None: ...


class AttemptStage(StrEnum):
    PRE_DISPATCH = "pre_dispatch"
    DISPATCH_POSSIBLE = "dispatch_possible"
    RESPONSE_RECEIVED = "response_received"
    COMPLETED = "completed"


class SearchUsageRepository(Protocol):
    async def start_attempt(
        self,
        *,
        operation_id: str,
        principal_id: str,
        provider_id: SearchProviderId,
        query_item_index: int,
        attempt_number: int,
    ) -> None: ...

    async def mark_stage(
        self,
        *,
        operation_id: str,
        provider_id: SearchProviderId,
        query_item_index: int,
        attempt_number: int,
        stage: AttemptStage,
        outcome_code: str | None = None,
        provider_request_id: str | None = None,
    ) -> None: ...


class ProviderAttemptError(Exception):
    """Safe normalized failure from exactly one provider request attempt."""

    def __init__(
        self,
        error: OperationError,
        *,
        stage: ExecutionStage,
        provider_request_id: str | None = None,
    ) -> None:
        self.error = error
        self.stage = stage
        self.provider_request_id = provider_request_id
        super().__init__(error.code)
