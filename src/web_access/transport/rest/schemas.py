"""Bounded operational REST response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from web_access.application.common.health import ServiceStatus


class LiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["alive"] = "alive"


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready", "unavailable"]


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: ServiceStatus
