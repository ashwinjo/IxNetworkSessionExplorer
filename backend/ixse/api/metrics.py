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


def update_session_metrics(
    session_id: str, server: str, utilized: bool, cp_active: bool, dp_active: bool
) -> None:
    """Set per-session utilization and plane-activity gauges."""
    ixse_session_utilized.labels(session=session_id, server=server).set(1 if utilized else 0)
    ixse_session_cp_active.labels(session=session_id, server=server).set(1 if cp_active else 0)
    ixse_session_dp_active.labels(session=session_id, server=server).set(1 if dp_active else 0)


def update_chassis_metrics(chassis_name: str, reachable: bool, ports_in_use: int) -> None:
    """Set per-chassis reachability and port-count gauges."""
    ixse_chassis_reachable.labels(chassis=chassis_name).set(1 if reachable else 0)
    ixse_ports_in_use.labels(chassis=chassis_name).set(ports_in_use)


def update_server_totals(server: str, session_count: int) -> None:
    """Set total session count for a server."""
    ixse_sessions_total.labels(server=server).set(session_count)


def clear_metrics() -> None:
    """Remove all tracked label combinations from every gauge in our registry.

    Safe to call between poll cycles to evict stale session labels.
    """
    for gauge in (
        ixse_session_utilized,
        ixse_session_cp_active,
        ixse_session_dp_active,
        ixse_sessions_total,
        ixse_chassis_reachable,
        ixse_ports_in_use,
    ):
        gauge.clear()
