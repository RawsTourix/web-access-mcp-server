"""Application-consumer port for transport-facing service metrics."""

from typing import Protocol


class Metrics(Protocol):
    def observe_http_request(
        self, *, method: str, route: str, status_class: str, duration_seconds: float
    ) -> None: ...

    def set_readiness(self, ready: bool) -> None: ...

    def render(self) -> bytes: ...
