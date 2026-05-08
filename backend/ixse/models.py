"""
Core data models: Session, SessionPort, PlaneStatus, ChassisHealth.

Defines dataclasses for representing IxNetwork sessions, port allocations,
plane (CP/DP) utilization status, and chassis health metrics.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionPort:
    """Physical port assignment within a session."""
    chassis_name: str
    chassis_host: str
    card: int
    port: int


@dataclass
class PlaneStatus:
    """Control plane + data plane activity status."""
    cp_active: bool
    dp_active: bool
    utilized: bool = field(init=False)

    def __post_init__(self):
        """Compute utilization as CP AND DP."""
        self.utilized = self.cp_active and self.dp_active


@dataclass
class Session:
    """IxNetwork session with port allocation and plane status."""
    id: str
    name: str
    state: str
    username: str
    ixnet_server: str
    ports: list[SessionPort] = field(default_factory=list)
    plane: Optional[PlaneStatus] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ChassisHealth:
    """Chassis reachability and port utilization metrics."""
    name: str
    host: str
    reachable: bool
    latency_ms: Optional[float] = None
    ports_in_use: int = 0
