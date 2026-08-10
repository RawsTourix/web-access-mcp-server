"""Uvicorn application factory; dependency clients start only inside lifespan."""

from fastapi import FastAPI

from web_access.core.config import Settings
from web_access.transport.mcp.server import create_control_plane


def create_app(settings: Settings | None = None) -> FastAPI:
    return create_control_plane(settings)
