"""
Plane detection logic: control plane (CP) and data plane (DP) activity.

Provides detect_cp() and detect_dp() functions that determine whether
an IxNetwork session has active protocols and/or active traffic.
Utilization = CP_ACTIVE AND DP_ACTIVE.
"""

from ixse.models import Session, PlaneStatus


def detect_cp(session: Session) -> bool:
    """
    Detect control plane (protocol) activity for a session.

    Queries RestPy topology/device group SessionStatus.
    Returns True if any device group has started protocols
    (status != "notStarted").

    Args:
        session: Session object with RestPy session reference.

    Returns:
        True if any protocol is active, False if all are notStarted.
    """
    pass


def detect_dp(session: Session) -> bool:
    """
    Detect data plane (traffic) activity for a session.

    Queries IxOS REST for TX/RX frame counters across all session ports.
    Returns True if any port has non-zero TX or RX frame count.

    Args:
        session: Session object with port list.

    Returns:
        True if any port has non-zero traffic, False otherwise.
    """
    pass


def compute_plane_status(session: Session) -> PlaneStatus:
    """
    Compute full plane status for a session.

    Evaluates CP and DP separately, then combines.

    Args:
        session: Session to evaluate.

    Returns:
        PlaneStatus with cp_active, dp_active, and utilized fields.
    """
    cp_active = detect_cp(session)
    dp_active = detect_dp(session)
    return PlaneStatus(cp_active=cp_active, dp_active=dp_active)
