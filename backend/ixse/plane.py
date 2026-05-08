"""
Plane detection logic: control plane (CP) and data plane (DP) activity.

Provides pure functions for determining whether an IxNetwork session has
active protocols (CP) and/or active traffic (DP).

Utilization = CP_ACTIVE OR DP_ACTIVE.

Design notes:
- detect_cp accepts any duck-typed RestPy session object (Any) so that unit
  tests can pass mocks without the ixnetwork_restpy library installed.
- detect_dp receives an explicit IxOSClient + port list rather than pulling
  them from a domain Session, keeping transport concerns out of this module.
- Both functions are pure and side-effect free (except logging).
- Both functions degrade conservatively on error: CP error → False (not active),
  DP error per-port → skip that port, continue checking the rest.
"""

from __future__ import annotations

import logging
from typing import Any

from ixse.ixos import IxOSClient, IxOSClientError
from ixse.models import PlaneStatus, SessionPort

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# RestPy 1.x DeviceGroup.Status values that indicate active protocols.
# (configured | error | mixed | notStarted | started | starting | stopping)
_ACTIVE_STATUSES = {"started", "starting", "mixed", "stopping"}


# ---------------------------------------------------------------------------
# Control Plane detection
# ---------------------------------------------------------------------------


def detect_cp_per_vport(vport_href: str, topologies: Any) -> bool:
    """Check if a single vport has active control-plane protocols.

    Walks each topology's Vports list to find topologies that include this
    vport, then checks their DeviceGroup Status.

    Args:
        vport_href: The RestPy href of the vport, e.g.
                    "/api/v1/sessions/3/ixnetwork/vport/1"
        topologies: RestPy Topology collection from session.Ixnetwork.Topology.find()

    Returns:
        True if any DeviceGroup in a topology bound to this vport is active.
    """
    try:
        for topo in topologies:
            topo_vport_hrefs = [str(v) for v in (getattr(topo, "Vports", []) or [])]
            if vport_href not in topo_vport_hrefs:
                continue
            for dg in topo.DeviceGroup.find():
                status = getattr(dg, "Status", None) or getattr(dg, "SessionStatus", None)  # noqa: SIM910
                if status is None:
                    continue
                if isinstance(status, list):
                    if any(s in _ACTIVE_STATUSES for s in status):
                        return True
                elif status in _ACTIVE_STATUSES:
                    return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Per-vport CP detection failed for %s: %s", vport_href, exc)
    return False


def detect_cp(session_obj: Any) -> bool:
    """
    Check if control plane (protocols) are active via a RestPy session object.

    Iterates Topology → DeviceGroup → SessionStatus.  Any status value that
    is not "notStarted" is treated as evidence of CP activity.

    SessionStatus may be a plain string or a list of strings depending on the
    RestPy version and topology configuration; both forms are handled.

    Conservative failure mode: if RestPy raises for any reason (connectivity
    loss, unexpected schema) the function returns False and logs a warning
    rather than propagating the exception to the poller.

    Args:
        session_obj: RestPy IxNetwork session object (duck-typed, accepts mock).

    Returns:
        True if ANY device group has a protocol running, False otherwise.
    """
    try:
        topologies = session_obj.Topology.find()
        for topo in topologies:
            device_groups = topo.DeviceGroup.find()
            for dg in device_groups:
                # RestPy 1.x uses DeviceGroup.Status; older versions used SessionStatus
                status = getattr(dg, "Status", None) or getattr(dg, "SessionStatus", None)  # noqa: SIM910
                if status is None:
                    continue
                if isinstance(status, list):
                    if any(s in _ACTIVE_STATUSES for s in status):
                        return True
                elif status in _ACTIVE_STATUSES:
                    return True
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("CP detection failed: %s", exc)
        return False  # Conservative: treat error as not-active


# ---------------------------------------------------------------------------
# Data Plane detection
# ---------------------------------------------------------------------------


def detect_dp(ixos_client: IxOSClient, ports: list[SessionPort]) -> bool:
    """
    Check if data plane (traffic) is running via IxOS port frame counters.

    Queries each port's TX and RX frame counts.  Returns True as soon as any
    port reports non-zero traffic.  Ports that raise IxOSClientError are
    skipped (logged as warnings) so a single unreachable port cannot mask
    activity on other ports.

    Args:
        ixos_client: IxOSClient connected to the chassis that owns the ports.
        ports: SessionPort list to check.  Empty list → False immediately.

    Returns:
        True if ANY port has tx_frames > 0 OR rx_frames > 0, False otherwise.
    """
    for port in ports:
        try:
            stats = ixos_client.get_port_stats(port.card, port.port)
            if stats.tx_frames > 0 or stats.rx_frames > 0:
                return True
        except IxOSClientError as exc:
            logger.warning(
                "DP detection failed for port %d/%d: %s",
                port.card,
                port.port,
                exc,
            )
            continue  # Skip this port, check others
    return False


# ---------------------------------------------------------------------------
# Combined status
# ---------------------------------------------------------------------------


def compute_plane_status(
    session_obj: Any,
    ixos_client: IxOSClient,
    ports: list[SessionPort],
) -> PlaneStatus:
    """
    Compute combined CP + DP plane status for a session.

    Runs detect_cp and detect_dp independently then combines into a
    PlaneStatus whose ``utilized`` field is auto-enforced by the model
    validator (cp_active OR dp_active).

    Args:
        session_obj: RestPy IxNetwork session object (duck-typed).
        ixos_client: IxOSClient for the chassis owning the session ports.
        ports: Physical ports belonging to this session.

    Returns:
        PlaneStatus(cp_active, dp_active, utilized=cp_active or dp_active).
    """
    cp_active = detect_cp(session_obj)
    dp_active = detect_dp(ixos_client, ports)
    return PlaneStatus(cp_active=cp_active, dp_active=dp_active)
