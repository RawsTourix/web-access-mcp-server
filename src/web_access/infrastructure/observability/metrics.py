"""Low-cardinality Prometheus foundation with app-local registries."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


@dataclass(frozen=True, slots=True)
class ServiceMetrics:
    registry: CollectorRegistry
    requests: Counter
    request_duration: Histogram
    readiness: Gauge
    search_provider_calls: Counter
    search_provider_duration: Histogram
    search_cache: Counter
    search_admission_rejections: Counter
    search_results: Histogram
    search_provider_timeouts: Counter
    search_internal_retries: Counter
    search_billable_attempts: Counter
    search_provider_readiness: Gauge

    def observe_http_request(
        self, *, method: str, route: str, status_class: str, duration_seconds: float
    ) -> None:
        self.requests.labels(method=method, route=route, status_class=status_class).inc()
        self.request_duration.labels(method=method, route=route).observe(duration_seconds)

    def set_readiness(self, ready: bool) -> None:
        self.readiness.set(1 if ready else 0)

    def observe_search_provider_call(
        self,
        *,
        provider: str,
        outcome: str,
        duration_seconds: float,
        result_count: int | None,
        timed_out: bool,
    ) -> None:
        self.search_provider_calls.labels(provider=provider, outcome=outcome).inc()
        self.search_provider_duration.labels(provider=provider, outcome=outcome).observe(
            duration_seconds
        )
        if result_count is not None:
            self.search_results.labels(provider=provider).observe(result_count)
        if timed_out:
            self.search_provider_timeouts.labels(provider=provider).inc()

    def observe_search_cache(self, *, provider: str, state: str) -> None:
        self.search_cache.labels(provider=provider, state=state).inc()

    def observe_search_admission_rejection(self, *, provider: str, kind: str) -> None:
        self.search_admission_rejections.labels(provider=provider, kind=kind).inc()

    def observe_search_retry(self, *, provider: str, reason: str) -> None:
        self.search_internal_retries.labels(provider=provider, reason=reason).inc()

    def observe_search_billable_attempt(self, *, provider: str, stage: str, outcome: str) -> None:
        self.search_billable_attempts.labels(provider=provider, stage=stage, outcome=outcome).inc()

    def set_search_provider_readiness(self, *, provider: str, status: str) -> None:
        for candidate in ("ready", "degraded", "unavailable"):
            self.search_provider_readiness.labels(provider=provider, status=candidate).set(
                1 if status == candidate else 0
            )

    def render(self) -> bytes:
        return generate_latest(self.registry)


def create_metrics() -> ServiceMetrics:
    registry = CollectorRegistry(auto_describe=True)
    return ServiceMetrics(
        registry=registry,
        requests=Counter(
            "web_access_http_requests_total",
            "HTTP requests observed by the Control Plane.",
            labelnames=("method", "route", "status_class"),
            registry=registry,
        ),
        request_duration=Histogram(
            "web_access_http_request_duration_seconds",
            "Control Plane HTTP request duration.",
            labelnames=("method", "route"),
            registry=registry,
        ),
        readiness=Gauge(
            "web_access_ready",
            "Whether the configured deployment profile is ready.",
            registry=registry,
        ),
        search_provider_calls=Counter(
            "web_access_search_provider_calls_total",
            "Bounded Search provider call outcomes.",
            labelnames=("provider", "outcome"),
            registry=registry,
        ),
        search_provider_duration=Histogram(
            "web_access_search_provider_duration_seconds",
            "Search provider attempt duration.",
            labelnames=("provider", "outcome"),
            registry=registry,
        ),
        search_cache=Counter(
            "web_access_search_cache_total",
            "Search cache lookup states.",
            labelnames=("provider", "state"),
            registry=registry,
        ),
        search_admission_rejections=Counter(
            "web_access_search_admission_rejections_total",
            "Search rate and concurrency admission rejections.",
            labelnames=("provider", "kind"),
            registry=registry,
        ),
        search_results=Histogram(
            "web_access_search_result_count",
            "Normalized result count per successful provider attempt.",
            labelnames=("provider",),
            registry=registry,
            buckets=(0, 1, 5, 10, 20, 50),
        ),
        search_provider_timeouts=Counter(
            "web_access_search_provider_timeouts_total",
            "Search provider timeouts.",
            labelnames=("provider",),
            registry=registry,
        ),
        search_internal_retries=Counter(
            "web_access_search_internal_retries_total",
            "Search internal retries by bounded reason class.",
            labelnames=("provider", "reason"),
            registry=registry,
        ),
        search_billable_attempts=Counter(
            "web_access_search_billable_attempts_total",
            "Durable billable Search attempt stage outcomes.",
            labelnames=("provider", "stage", "outcome"),
            registry=registry,
        ),
        search_provider_readiness=Gauge(
            "web_access_search_provider_readiness",
            "Independent Search provider readiness state.",
            labelnames=("provider", "status"),
            registry=registry,
        ),
    )
