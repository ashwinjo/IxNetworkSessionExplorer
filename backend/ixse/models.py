"""
Core Pydantic v2 domain models for IxNetworkSessionExplorer.

All fields are strictly typed. No use of Any.
Datetime fields are timezone-aware (UTC enforcement via AwareDatetime).
Computed fields (utilized) are enforced via model_validator — caller-supplied
values are overwritten to guarantee cp_active AND dp_active semantics.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class SessionPort(BaseModel):
    """Physical port assignment within a session."""

    chassis_name: str = Field(..., description="Chassis label, e.g. 'lab-01'")
    card: int = Field(..., gt=0, description="Card number (1-indexed, must be > 0)")
    port: int = Field(..., gt=0, description="Port number (1-indexed, must be > 0)")

    model_config = {"frozen": False}


class PlaneStatus(BaseModel):
    """Control plane + data plane activity status for a session."""

    model_config = ConfigDict(frozen=True)

    cp_active: bool = Field(..., description="True when control-plane protocols are started")
    dp_active: bool = Field(..., description="True when data-plane traffic is flowing")
    utilized: bool = Field(
        default=False,
        description="cp_active AND dp_active (auto-computed)",
        json_schema_extra={"readOnly": True, "computed": True},
    )

    @model_validator(mode="after")
    def compute_utilized(self) -> "PlaneStatus":
        """Recompute utilized so it always equals cp_active AND dp_active.

        Uses object.__setattr__ because frozen=True blocks normal assignment.
        This runs after field assignment, overwriting any caller-supplied value.
        """
        object.__setattr__(self, "utilized", self.cp_active and self.dp_active)
        return self


class Session(BaseModel):
    """IxNetwork session with port allocation, plane status, and metadata."""

    id: str = Field(..., description="Session ID as reported by IxNetwork")
    name: str = Field(..., description="Human-readable session name")
    ixnet_server: str = Field(..., description="IxNetwork server name from config")
    ports: list[SessionPort] = Field(
        default_factory=list, description="Physical ports owned by this session"
    )
    cp_active: bool = Field(..., description="Control-plane protocols active")
    dp_active: bool = Field(..., description="Data-plane traffic running")
    utilized: bool = Field(
        default=False,
        description="cp_active AND dp_active (auto-computed)",
        json_schema_extra={"readOnly": True, "computed": True},
    )
    tags: list[str] = Field(default_factory=list, description="Operator-assigned labels")
    last_polled: AwareDatetime = Field(
        ..., description="UTC timestamp of the last successful poll"
    )

    @model_validator(mode="after")
    def compute_utilized(self) -> "Session":
        """Recompute utilized so it always equals cp_active AND dp_active.

        Runs after field assignment; overwrites any caller-supplied value.
        """
        self.utilized = self.cp_active and self.dp_active
        return self


class PollStatus(BaseModel):
    """Background poller state snapshot."""

    last_polled_at: AwareDatetime | None = Field(
        default=None, description="When the last poll cycle completed (UTC)"
    )
    next_scheduled: AwareDatetime | None = Field(
        default=None, description="When the next poll cycle is expected to start (UTC)"
    )
    is_polling: bool = Field(default=False, description="True while a poll cycle is in progress")


class ChassisHealth(BaseModel):
    """Reachability and utilisation summary for a single IxOS chassis."""

    name: str = Field(..., description="Chassis label from config")
    host: str = Field(..., description="Chassis IP or hostname")
    reachable: bool = Field(..., description="True if the chassis responded to the last health check")
    latency_ms: float | None = Field(default=None, description="Round-trip latency in milliseconds")
    ports_in_use: int = Field(default=0, description="Number of ports assigned to active sessions")
    last_checked: AwareDatetime | None = Field(
        default=None, description="UTC timestamp of the last health check"
    )
