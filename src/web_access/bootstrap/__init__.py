"""Application composition root."""

from web_access.bootstrap.container import RuntimeContainer
from web_access.bootstrap.lifespan import runtime_lifespan

__all__ = ["RuntimeContainer", "runtime_lifespan"]
