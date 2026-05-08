"""
Unit tests for ixse/client.py — TDD-first.

Tests cover:
1. list_sessions() returns list of SessionSummary
2. get_session(id) returns SessionDetail with correct fields
3. Timeout triggers retry — mock raises Exception first time, succeeds second
4. Two consecutive timeouts raise ClientError
5. kill_session(id) calls remove on the session object and verifies it's gone
6. connect() when restpy not available raises ClientError
7. get_raw_sessions() returns raw session objects (for CP detection)

All tests mock TestPlatform so ixnetwork_restpy is not required.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from ixse.client import ClientError, RestPyClient, SessionDetail, SessionSummary


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_session(
    session_id: str = "1", name: str = "bgp-test", state: str = "Active"
) -> MagicMock:
    """Return a MagicMock that mimics a RestPy Session object from Sessions.find()."""
    s = MagicMock()
    s.Id = session_id
    s.Name = name
    s.State = state
    s.Ixnetwork.Topology.find.return_value = []
    s.Ixnetwork.Vport.find.return_value = []
    return s


def _make_mock_platform(sessions: list[MagicMock] | None = None) -> MagicMock:
    """Return a MagicMock mimicking a TestPlatform whose Sessions.find() returns sessions."""
    if sessions is None:
        sessions = [_make_mock_session()]
    platform = MagicMock()
    platform.Sessions.find.return_value = sessions
    return platform


def _connected_client(
    mock_platform: MagicMock,
    host: str = "10.0.0.1",
    rest_port: int | None = None,
) -> RestPyClient:
    """Convenience: create a RestPyClient that is already connected via mock_platform."""
    with patch("ixse.client._RESTPY_AVAILABLE", True), \
         patch("ixse.client.TestPlatform", return_value=mock_platform):
        client = RestPyClient(host, "admin", "secret", rest_port)
        client.connect()
    return client


# ---------------------------------------------------------------------------
# Test 1: list_sessions() returns list[SessionSummary]
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_returns_session_summary_list(self):
        mock_sessions = [
            _make_mock_session("1", "bgp-test", "Active"),
            _make_mock_session("2", "ospf-lab", "stopped"),
        ]
        platform = _make_mock_platform(mock_sessions)
        client = _connected_client(platform)

        result = client.list_sessions()

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(s, SessionSummary) for s in result)

    def test_session_summary_fields(self):
        platform = _make_mock_platform([_make_mock_session("42", "my-session", "Active")])
        client = _connected_client(platform)

        result = client.list_sessions()

        s = result[0]
        assert s.id == "42"
        assert s.name == "my-session"
        assert s.state == "Active"

    def test_empty_server_returns_empty_list(self):
        platform = _make_mock_platform([])
        client = _connected_client(platform)

        assert client.list_sessions() == []


# ---------------------------------------------------------------------------
# Test 2: get_session(id) returns SessionDetail with correct fields
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_returns_session_detail(self):
        sess = _make_mock_session("7", "topo-test", "Active")
        topo1, topo2 = MagicMock(), MagicMock()
        sess.Ixnetwork.Topology.find.return_value = [topo1, topo2]

        vp1, vp2 = MagicMock(), MagicMock()
        vp1.Name = "Ethernet - 001"
        vp1.AssignedTo = "10.0.0.1:1:1"
        vp2.Name = "Ethernet - 002"
        vp2.AssignedTo = "10.0.0.1:1:2"
        sess.Ixnetwork.Vport.find.return_value = [vp1, vp2]

        platform = _make_mock_platform([sess])
        client = _connected_client(platform)

        detail = client.get_session("7")

        assert isinstance(detail, SessionDetail)
        assert detail.id == "7"
        assert detail.name == "topo-test"
        assert detail.topology_count == 2
        assert len(detail.ports) == 2

    def test_get_session_not_found_raises_client_error(self):
        client = _connected_client(_make_mock_platform([]))
        with pytest.raises(ClientError, match="not found"):
            client.get_session("999")

    def test_port_data_is_list_of_dicts(self):
        sess = _make_mock_session("3", "port-test", "Active")
        vp = MagicMock()
        vp.Name = "Ethernet - 001"
        vp.AssignedTo = "10.0.0.1:2:3"
        sess.Ixnetwork.Vport.find.return_value = [vp]

        client = _connected_client(_make_mock_platform([sess]))
        detail = client.get_session("3")

        assert isinstance(detail.ports, list)
        assert isinstance(detail.ports[0], dict)
        assert "name" in detail.ports[0]
        assert "assigned_to" in detail.ports[0]


# ---------------------------------------------------------------------------
# Test 3: Timeout triggers retry — first call raises, second succeeds
# ---------------------------------------------------------------------------


class TestRetryOnTimeout:
    def test_single_timeout_retries_and_succeeds(self):
        mock_sessions = [_make_mock_session("1", "bgp-test", "Active")]
        call_count = 0

        def flaky_find():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("timeout")
            return mock_sessions

        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = flaky_find
        client = _connected_client(platform)

        result = client.list_sessions()

        assert len(result) == 1
        assert call_count == 2

    def test_retry_preserves_correct_data(self):
        mock_sessions = [_make_mock_session("5", "retry-session", "Active")]
        attempt = 0

        def flaky_find():
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise TimeoutError("connection timed out")
            return mock_sessions

        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = flaky_find
        client = _connected_client(platform)

        result = client.list_sessions()

        assert result[0].id == "5"
        assert result[0].name == "retry-session"


# ---------------------------------------------------------------------------
# Test 4: Two timeouts raise ClientError
# ---------------------------------------------------------------------------


class TestDoubleTimeoutRaisesClientError:
    def test_two_timeouts_raise_client_error(self):
        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = ConnectionError("timeout every time")
        client = _connected_client(platform)

        with pytest.raises(ClientError):
            client.list_sessions()

    def test_error_message_contains_host(self):
        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = TimeoutError("socket timed out")
        client = _connected_client(platform)

        with pytest.raises(ClientError) as exc_info:
            client.list_sessions()

        assert "10.0.0.1" in str(exc_info.value)

    def test_retry_count_is_exactly_two(self):
        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = ConnectionError("dead")
        client = _connected_client(platform)

        with pytest.raises(ClientError):
            client.list_sessions()

        assert platform.Sessions.find.call_count == 2


# ---------------------------------------------------------------------------
# Test 5: kill_session(id) removes session and verifies it's gone
# ---------------------------------------------------------------------------


class TestKillSession:
    def test_kill_calls_remove_on_session(self):
        sess = _make_mock_session("10", "dead-session", "Active")
        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = [
            [sess],  # locate session
            [],      # verification: gone
        ]
        client = _connected_client(platform)

        client.kill_session("10")

        sess.remove.assert_called_once()

    def test_kill_nonexistent_session_raises_client_error(self):
        client = _connected_client(_make_mock_platform([]))
        with pytest.raises(ClientError, match="not found"):
            client.kill_session("999")

    def test_kill_verifies_session_gone_after_remove(self):
        sess = _make_mock_session("20", "to-kill", "Active")
        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = [
            [sess],  # locate session
            [],      # post-remove: empty = success
        ]
        client = _connected_client(platform)

        client.kill_session("20")  # must not raise

        assert platform.Sessions.find.call_count == 2

    def test_kill_raises_if_session_still_present_after_remove(self):
        sess = _make_mock_session("30", "stubborn", "Active")
        platform = _make_mock_platform()
        platform.Sessions.find.side_effect = [
            [sess],  # locate session
            [sess],  # verification: still present — kill failed
        ]
        client = _connected_client(platform)

        with pytest.raises(ClientError, match="still present"):
            client.kill_session("30")


# ---------------------------------------------------------------------------
# Test 6: connect() when restpy not available raises ClientError
# ---------------------------------------------------------------------------


class TestRestpyNotAvailable:
    def test_connect_raises_when_restpy_missing(self):
        with patch("ixse.client._RESTPY_AVAILABLE", False):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            with pytest.raises(ClientError, match="ixnetwork_restpy is not installed"):
                client.connect()

    def test_list_sessions_raises_when_not_connected(self):
        """list_sessions() before connect() must raise ClientError."""
        client = RestPyClient("10.0.0.1", "admin", "secret")
        with pytest.raises(ClientError, match="not connected"):
            client.list_sessions()

    def test_error_message_contains_install_hint(self):
        with patch("ixse.client._RESTPY_AVAILABLE", False):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            with pytest.raises(ClientError) as exc_info:
                client.connect()
        assert "pip install ixnetwork-restpy" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 7: get_raw_sessions() returns raw objects (used by poller for CP detect)
# ---------------------------------------------------------------------------


class TestGetRawSessions:
    def test_returns_raw_objects(self):
        sess1 = _make_mock_session("1")
        sess2 = _make_mock_session("2")
        platform = _make_mock_platform([sess1, sess2])
        client = _connected_client(platform)

        raw = client.get_raw_sessions()

        assert raw == [sess1, sess2]

    def test_empty_server_returns_empty_list(self):
        client = _connected_client(_make_mock_platform([]))
        assert client.get_raw_sessions() == []


# ---------------------------------------------------------------------------
# Test 8: disconnect() is safe to call
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_when_connected(self):
        client = _connected_client(_make_mock_platform())
        client.disconnect()  # must not raise

    def test_disconnect_when_not_connected_is_safe(self):
        client = RestPyClient("10.0.0.1", "admin", "secret")
        client.disconnect()  # must not raise (idempotent)

    def test_after_disconnect_list_sessions_raises(self):
        client = _connected_client(_make_mock_platform())
        client.disconnect()
        with pytest.raises(ClientError, match="not connected"):
            client.list_sessions()
