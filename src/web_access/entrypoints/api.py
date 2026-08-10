"""Uvicorn application factory; dependency clients start only inside lifespan."""

from fastapi import FastAPI

from web_access.bootstrap.app import create_control_plane
from web_access.core.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    return create_control_plane(settings)
