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

    def observe_http_request(
        self, *, method: str, route: str, status_class: str, duration_seconds: float
    ) -> None:
        self.requests.labels(method=method, route=route, status_class=status_class).inc()
        self.request_duration.labels(method=method, route=route).observe(duration_seconds)

    def set_readiness(self, ready: bool) -> None:
        self.readiness.set(1 if ready else 0)

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
    )
