"""
Prometheus metrics: gauges for session utilization and chassis health.

Defines metrics exported at /metrics endpoint in OpenMetrics format.
Includes per-session CP/DP activity, utilization, and fleet-wide totals.
"""

from prometheus_client import Gauge, CollectorRegistry


# Create a separate registry for this application
registry = CollectorRegistry()

# Session-level metrics
ixse_session_utilized = Gauge(
    "ixse_session_utilized",
    "Is this session utilizing both CP and DP?",
    labelnames=["session", "server"],
    registry=registry
)

ixse_session_cp_active = Gauge(
    "ixse_session_cp_active",
    "Is control plane (protocols) active?",
    labelnames=["session", "server"],
    registry=registry
)

ixse_session_dp_active = Gauge(
    "ixse_session_dp_active",
    "Is data plane (traffic) active?",
    labelnames=["session", "server"],
    registry=registry
)

# Fleet-level metrics
ixse_sessions_total = Gauge(
    "ixse_sessions_total",
    "Total number of sessions per server",
    labelnames=["server"],
    registry=registry
)

# Chassis metrics
ixse_chassis_reachable = Gauge(
    "ixse_chassis_reachable",
    "Is chassis reachable?",
    labelnames=["chassis"],
    registry=registry
)

ixse_ports_in_use = Gauge(
    "ixse_ports_in_use",
    "Number of ports in active sessions on chassis",
    labelnames=["chassis"],
    registry=registry
)


def update_session_metrics(session_id: str, server: str, utilized: bool, cp_active: bool, dp_active: bool) -> None:
    """Update metrics for a session."""
    pass


def update_chassis_metrics(chassis_name: str, reachable: bool, ports_in_use: int) -> None:
    """Update metrics for a chassis."""
    pass


def update_server_totals(server: str, session_count: int) -> None:
    """Update total session count for a server."""
    pass


def clear_metrics() -> None:
    """Clear all metrics."""
    pass
