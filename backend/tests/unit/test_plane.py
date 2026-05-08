"""
Unit tests for ixse/plane.py — CP/DP utilization detection.

TDD: written before the implementation.

Coverage:
  1.  detect_cp — topology with active DG → True
  2.  detect_cp — all DGs "notStarted" → False
  3.  detect_cp — no topologies → False
  4.  detect_cp — SessionStatus is list with one active entry → True
  5.  detect_cp — RestPy exception raised → False (graceful degradation)
  6.  detect_dp — port with tx_frames > 0 → True
  7.  detect_dp — port with rx_frames > 0 → True
  8.  detect_dp — all ports have zero frames → False
  9.  detect_dp — IxOSClientError on one port → skips, checks remaining
  10. detect_dp — no ports → False
  11. compute_plane_status — cp=True, dp=True → utilized=True
  12. compute_plane_status — cp=True, dp=False → utilized=False
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ixse.ixos import IxOSClientError, PortStats
from ixse.models import PlaneStatus, SessionPort
from ixse.plane import compute_plane_status, detect_cp, detect_dp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dg(status: str | list[str]) -> MagicMock:
    """Create a mock DeviceGroup with the given SessionStatus."""
    dg = MagicMock()
    dg.SessionStatus = status
    return dg


def _make_topo(*dg_statuses: str | list[str]) -> MagicMock:
    """Create a mock Topology containing DeviceGroups with given statuses."""
    topo = MagicMock()
    dgs = [_make_dg(s) for s in dg_statuses]
    topo.DeviceGroup.find.return_value = dgs
    return topo


def _make_session_obj(topologies: list[MagicMock]) -> MagicMock:
    """Create a mock RestPy session object with the given topology list."""
    sess = MagicMock()
    sess.Topology.find.return_value = topologies
    return sess


def _make_port(card: int = 1, port: int = 1, chassis_name: str = "lab-01") -> SessionPort:
    return SessionPort(chassis_name=chassis_name, card=card, port=port)


def _make_ixos_client(*port_stats: PortStats | type[IxOSClientError]) -> MagicMock:
    """
    Return a mock IxOSClient whose get_port_stats() returns successive values.

    Pass PortStats instances for normal returns.
    Pass IxOSClientError (the class) to raise that error for that call.
    """
    client = MagicMock()
    side_effects: list = []
    for item in port_stats:
        if item is IxOSClientError or (isinstance(item, type) and issubclass(item, IxOSClientError)):
            side_effects.append(IxOSClientError("simulated IxOS error"))
        else:
            side_effects.append(item)
    client.get_port_stats.side_effect = side_effects
    return client


# ---------------------------------------------------------------------------
# detect_cp
# ---------------------------------------------------------------------------


class TestDetectCP:
    # 1. Topology with one active DG → True
    def test_active_device_group_returns_true(self):
        topo = _make_topo("started")
        sess = _make_session_obj([topo])
        assert detect_cp(sess) is True

    # 2. All DGs "notStarted" → False
    def test_all_not_started_returns_false(self):
        topo = _make_topo("notStarted", "notStarted")
        sess = _make_session_obj([topo])
        assert detect_cp(sess) is False

    # 3. No topologies → False
    def test_no_topologies_returns_false(self):
        sess = _make_session_obj([])
        assert detect_cp(sess) is False

    # 4. SessionStatus is a list containing one active entry → True
    def test_status_as_list_with_active_entry_returns_true(self):
        # Mixed list: one notStarted, one started
        topo = _make_topo(["notStarted", "started"])
        sess = _make_session_obj([topo])
        assert detect_cp(sess) is True

    # 4b. SessionStatus is a list where ALL are notStarted → False
    def test_status_as_list_all_not_started_returns_false(self):
        topo = _make_topo(["notStarted", "notStarted"])
        sess = _make_session_obj([topo])
        assert detect_cp(sess) is False

    # 5. RestPy exception raised → False (graceful degradation)
    def test_restpy_exception_returns_false(self):
        sess = MagicMock()
        sess.Topology.find.side_effect = RuntimeError("RestPy connection lost")
        assert detect_cp(sess) is False

    # Extra: multiple topologies, second one has active DG → True
    def test_second_topology_active_returns_true(self):
        topo1 = _make_topo("notStarted")
        topo2 = _make_topo("started")
        sess = _make_session_obj([topo1, topo2])
        assert detect_cp(sess) is True

    # Extra: multiple topologies, none active → False
    def test_multiple_topologies_none_active_returns_false(self):
        topo1 = _make_topo("notStarted")
        topo2 = _make_topo("notStarted")
        sess = _make_session_obj([topo1, topo2])
        assert detect_cp(sess) is False


# ---------------------------------------------------------------------------
# detect_dp
# ---------------------------------------------------------------------------


class TestDetectDP:
    # 6. Port with tx_frames > 0 → True
    def test_tx_frames_nonzero_returns_true(self):
        port = _make_port()
        stats = PortStats(tx_frames=100, rx_frames=0, port_state="up")
        client = _make_ixos_client(stats)
        assert detect_dp(client, [port]) is True

    # 7. Port with rx_frames > 0 → True
    def test_rx_frames_nonzero_returns_true(self):
        port = _make_port()
        stats = PortStats(tx_frames=0, rx_frames=50, port_state="up")
        client = _make_ixos_client(stats)
        assert detect_dp(client, [port]) is True

    # 8. All ports have zero frames → False
    def test_all_zero_frames_returns_false(self):
        ports = [_make_port(card=1, port=1), _make_port(card=1, port=2)]
        stats_zero = PortStats(tx_frames=0, rx_frames=0, port_state="up")
        client = _make_ixos_client(stats_zero, stats_zero)
        assert detect_dp(client, ports) is False

    # 9. IxOSClientError on first port → skips it, checks second port which has traffic → True
    def test_ixos_error_on_first_port_skips_to_next(self):
        ports = [_make_port(card=1, port=1), _make_port(card=1, port=2)]
        stats_active = PortStats(tx_frames=200, rx_frames=0, port_state="up")
        client = _make_ixos_client(IxOSClientError, stats_active)
        assert detect_dp(client, ports) is True

    # 9b. IxOSClientError on all ports → False (all skipped)
    def test_ixos_error_on_all_ports_returns_false(self):
        ports = [_make_port(card=1, port=1), _make_port(card=1, port=2)]
        client = _make_ixos_client(IxOSClientError, IxOSClientError)
        assert detect_dp(client, ports) is False

    # 10. No ports → False
    def test_no_ports_returns_false(self):
        client = MagicMock()
        assert detect_dp(client, []) is False
        client.get_port_stats.assert_not_called()

    # Extra: both tx and rx nonzero → True (short-circuits on first port)
    def test_both_tx_and_rx_nonzero_returns_true(self):
        port = _make_port()
        stats = PortStats(tx_frames=1000, rx_frames=500, port_state="up")
        client = _make_ixos_client(stats)
        assert detect_dp(client, [port]) is True


# ---------------------------------------------------------------------------
# compute_plane_status
# ---------------------------------------------------------------------------


class TestComputePlaneStatus:
    # 11. cp=True, dp=True → utilized=True
    def test_both_active_returns_utilized_true(self):
        sess = _make_session_obj([_make_topo("started")])
        port = _make_port()
        stats = PortStats(tx_frames=100, rx_frames=0, port_state="up")
        client = _make_ixos_client(stats)

        result = compute_plane_status(sess, client, [port])

        assert isinstance(result, PlaneStatus)
        assert result.cp_active is True
        assert result.dp_active is True
        assert result.utilized is True

    # 12. cp=True, dp=False → utilized=False
    def test_cp_active_dp_inactive_returns_utilized_false(self):
        sess = _make_session_obj([_make_topo("started")])
        port = _make_port()
        stats = PortStats(tx_frames=0, rx_frames=0, port_state="up")
        client = _make_ixos_client(stats)

        result = compute_plane_status(sess, client, [port])

        assert result.cp_active is True
        assert result.dp_active is False
        assert result.utilized is False

    # Extra: cp=False, dp=True → utilized=False
    def test_cp_inactive_dp_active_returns_utilized_false(self):
        sess = _make_session_obj([_make_topo("notStarted")])
        port = _make_port()
        stats = PortStats(tx_frames=0, rx_frames=500, port_state="up")
        client = _make_ixos_client(stats)

        result = compute_plane_status(sess, client, [port])

        assert result.cp_active is False
        assert result.dp_active is True
        assert result.utilized is False

    # Extra: both inactive → utilized=False
    def test_both_inactive_returns_utilized_false(self):
        sess = _make_session_obj([])
        client = MagicMock()

        result = compute_plane_status(sess, client, [])

        assert result.cp_active is False
        assert result.dp_active is False
        assert result.utilized is False
