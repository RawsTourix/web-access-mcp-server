"""Application-owned Search provider, cache, admission, and usage ports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

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


class RateAdmissionStatus(StrEnum):
    ALLOWED = "allowed"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RateAdmission:
    status: RateAdmissionStatus
    retry_after_seconds: float | None = None

    @property
    def allowed(self) -> bool:
        return self.status is RateAdmissionStatus.ALLOWED


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
        retry_reason: str | None = None,
        provider_request_id: str | None = None,
    ) -> None: ...


class SearchUsageUnitOfWork(Protocol):
    @property
    def usage(self) -> SearchUsageRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class SearchUsageUnitOfWorkFactory(Protocol):
    def __call__(self) -> SearchUsageUnitOfWork: ...


class SearchUsageUnavailable(RuntimeError):
    """Durable billable-attempt evidence cannot be persisted."""


class SearchTelemetry(Protocol):
    """Synchronous, bounded-label telemetry consumed by Search orchestration."""

    def observe_cache(self, provider_id: SearchProviderId, state: CacheLookupState) -> None: ...

    def observe_admission_rejection(self, provider_id: SearchProviderId, kind: str) -> None: ...

    def observe_internal_retry(self, provider_id: SearchProviderId, reason: str) -> None: ...

    def observe_billable_attempt(
        self, provider_id: SearchProviderId, stage: AttemptStage, outcome: str
    ) -> None: ...

    def observe_provider_readiness(self, provider_id: SearchProviderId, status: str) -> None: ...


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
