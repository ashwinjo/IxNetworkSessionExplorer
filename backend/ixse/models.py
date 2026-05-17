"""
Core Pydantic v2 domain models for IxNetworkSessionExplorer.

All fields are strictly typed. No use of Any.
Datetime fields are timezone-aware (UTC enforcement via AwareDatetime).
Computed fields (utilized) are enforced via model_validator — caller-supplied
values are overwritten to guarantee cp_active OR dp_active semantics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# Possible values from IxNetwork AppErrors.Error.ErrorLevel
_ERROR_LEVEL_KERROR = "kError"


class LldpPeerInfo(BaseModel):
    """LLDP neighbor information learned on a physical port via IxNetwork Locations API."""

    model_config = ConfigDict(frozen=True)

    peer_chassis_id: str = Field(default="", description="LLDP neighbor chassis identifier (MAC)")
    peer_description: str = Field(default="", description="LLDP neighbor port description")
    peer_hold_time: int = Field(default=0, description="LLDP advertised hold time in seconds")
    peer_ip_address: str = Field(default="", description="LLDP neighbor IP address")
    peer_port_id: str = Field(default="", description="LLDP neighbor port identifier")
    peer_system_name: str = Field(default="", description="LLDP neighbor system name")
    peer_system_description: str = Field(
        default="", description="LLDP neighbor system description"
    )

    @property
    def has_peer(self) -> bool:
        """True if at least one LLDP neighbor field was populated."""
        return bool(self.peer_system_name or self.peer_chassis_id or self.peer_port_id)


class SessionPort(BaseModel):
    """Physical port assignment within a session."""

    chassis_name: str = Field(..., description="Chassis IP or label from AssignedTo")
    card: int = Field(..., gt=0, description="Card number (1-indexed, must be > 0)")
    port: int = Field(..., gt=0, description="Port number (1-indexed, must be > 0)")

    # Enriched from Vport.find()
    vport_name: str = Field(default="", description="Logical vport name (Vport.Name)")
    fully_qualified_port_name: str = Field(
        default="",
        description="Chassis physical port label from Vport.FullyQualifiedPortName (e.g. '2.1')",
    )
    connection_state: str = Field(
        default="",
        description=(
            "Physical link state: connectedLinkUp | connectedLinkDown | "
            "notConnected | unassigned"
        ),
    )
    vport_type: str = Field(default="", description="Port type, e.g. 'tenFortyHundredGigLan'")
    actual_speed: int = Field(default=0, description="Negotiated speed in Mbps")

    # LLDP neighbor info — populated from IxNetwork Locations.Ports API
    lldp_peer: LldpPeerInfo | None = Field(
        default=None, description="LLDP neighbor info discovered on this port (None if unavailable)"
    )

    # Port-level plane status — utilization is a per-port attribute
    cp_active: bool = Field(default=False, description="Control-plane protocols active on this port")
    dp_active: bool = Field(default=False, description="Data-plane traffic flowing on this port")
    utilized: bool = Field(
        default=False,
        description="cp_active OR dp_active for this port (auto-computed)",
    )

    model_config = {"frozen": False}

    @model_validator(mode="after")
    def compute_utilized(self) -> "SessionPort":
        self.utilized = self.cp_active or self.dp_active
        return self


class PlaneStatus(BaseModel):
    """Control plane + data plane activity status for a session."""

    model_config = ConfigDict(frozen=True)

    cp_active: bool = Field(..., description="True when control-plane protocols are started")
    dp_active: bool = Field(..., description="True when data-plane traffic is flowing")
    utilized: bool = Field(
        default=False,
        description="cp_active OR dp_active (auto-computed)",
        json_schema_extra={"readOnly": True, "computed": True},
    )

    @model_validator(mode="after")
    def compute_utilized(self) -> "PlaneStatus":
        """Recompute utilized so it always equals cp_active OR dp_active.

        Uses object.__setattr__ because frozen=True blocks normal assignment.
        This runs after field assignment, overwriting any caller-supplied value.
        """
        object.__setattr__(self, "utilized", self.cp_active or self.dp_active)
        return self


class Session(BaseModel):
    """IxNetwork session with port allocation, plane status, and metadata.

    cp_active / dp_active / utilized are session-level summaries derived from
    the port list: True if ANY port has the corresponding flag set.
    Callers should not set these directly — the model_validator overwrites them.
    """

    id: str = Field(..., description="Session ID as reported by IxNetwork")
    name: str = Field(..., description="Human-readable session name")
    username: str = Field(default="", description="IxNetwork user who owns this session")
    ixnet_server: str = Field(..., description="IxNetwork server name from config")
    ports: list[SessionPort] = Field(
        default_factory=list, description="Physical ports owned by this session"
    )
    # Session-level summaries — derived from ports by model_validator
    cp_active: bool = Field(
        default=False,
        description="True when ANY port has active CP protocols (derived from ports)",
        json_schema_extra={"readOnly": True, "computed": True},
    )
    dp_active: bool = Field(
        default=False,
        description="True when ANY port has active DP traffic (derived from ports)",
        json_schema_extra={"readOnly": True, "computed": True},
    )
    utilized: bool = Field(
        default=False,
        description="True when ANY port is utilized cp AND dp (derived from ports)",
        json_schema_extra={"readOnly": True, "computed": True},
    )
    tags: list[str] = Field(default_factory=list, description="Operator-assigned labels")
    last_polled: AwareDatetime = Field(
        ..., description="UTC timestamp of the last successful poll"
    )

    # ── Session state & error fields (populated from IxNetwork Globals.AppErrors) ──
    session_state: str = Field(
        default="",
        description=(
            "Raw IxNetwork session state string "
            "(e.g. 'Active', 'stopped', 'Initial')"
        ),
    )
    error_status: Literal["NOERROR", "ERROR"] = Field(
        default="NOERROR",
        description="ERROR when any kError-level AppErrors are present, NOERROR otherwise",
    )
    error_count: int = Field(
        default=0,
        description="Total AppErrors.ErrorCount reported by IxNetwork",
    )
    error_list: list[str] = Field(
        default_factory=list,
        description="Names of all kError-level AppErrors on this session",
    )

    @model_validator(mode="after")
    def derive_plane_from_ports(self) -> "Session":
        """Derive session-level plane status from the union of all port statuses.

        cp_active  = ANY port has CP active
        dp_active  = ANY port has DP active
        utilized   = cp_active OR dp_active  (session is in-use if either plane is active)
        """
        self.cp_active = any(p.cp_active for p in self.ports)
        self.dp_active = any(p.dp_active for p in self.ports)
        self.utilized  = self.cp_active or self.dp_active
        return self


class IxNetworkWebSnapshot(BaseModel):
    """Result of probing IxNetwork Web HTTPS auth (standalone vs on-chassis UI)."""

    deployment: Literal["standalone", "onChassis"] | None = Field(
        default=None,
        description="Determined from which auth path returned an apiKey",
    )
    heartbeat: Literal["green", "yellow", "red"] = Field(
        ...,
        description="green=authenticated; red=unreachable; yellow=other failure",
    )
    auth_path: str | None = Field(
        default=None, description="Winning auth URI path when heartbeat is green"
    )
    detail: str | None = Field(default=None, description="Diagnostic when not green")
    checked_at: AwareDatetime | None = Field(default=None, description="UTC probe time")
    ixnetwork_version: str | None = Field(
        default=None,
        description="Version of the IxNetwork (ixnrest) product from system info API",
    )


class PollStatus(BaseModel):
    """Background poller state snapshot."""

    last_polled_at: AwareDatetime | None = Field(
        default=None, description="When the last poll cycle completed (UTC)"
    )
    next_scheduled: AwareDatetime | None = Field(
        default=None, description="When the next poll cycle is expected to start (UTC)"
    )
    is_polling: bool = Field(default=False, description="True while a poll cycle is in progress")


class KcosInfo(BaseModel):
    """Version strings extracted from the KCOS SSH welcome banner."""

    kcos_aresone: str = Field(..., description="kcos-aresone version (e.g. '1.2.156')")
    nucleon_kcos: str = Field(..., description="nucleon-kcos version (e.g. '2.14.2-49')")


class ServerEntry(BaseModel):
    """IxNetwork server connection parameters stored in the DB."""

    name: str = Field(..., description="Unique server label")
    host: str = Field(..., description="Hostname or IP address")
    username: str = Field(..., description="Login username")
    password: str = Field(default="", description="Login password (stored as-is; lab use only)")
    rest_port: int | None = Field(default=None, description="REST port (None = RestPy auto-detect)")
    tags: list[str] = Field(default_factory=list, description="Operator-assigned labels")
    kcos_info: KcosInfo | None = Field(
        default=None, description="KCOS platform versions detected via SSH probe; None if not KCOS"
    )


class ServerEntryPublic(BaseModel):
    """Server entry safe for API responses — password masked."""

    name: str
    host: str
    username: str
    rest_port: int | None = None
    tags: list[str] = Field(default_factory=list)
    kcos_info: KcosInfo | None = None


class PollConfig(BaseModel):
    """Poller configuration — interval persisted in the DB."""

    interval_seconds: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Poll interval in seconds (10–3600)",
    )


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
