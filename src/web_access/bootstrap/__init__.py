"""Application composition root."""

from web_access.bootstrap.app import assemble_control_plane, create_control_plane
from web_access.bootstrap.container import RuntimeContainer
from web_access.bootstrap.lifespan import runtime_lifespan

__all__ = [
    "RuntimeContainer",
    "assemble_control_plane",
    "create_control_plane",
    "runtime_lifespan",
]
