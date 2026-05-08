"""
Unit tests for ixse/client.py — TDD-first.

Tests cover:
1. list_sessions() returns list of SessionSummary
2. get_session(id) returns SessionDetail with correct fields
3. Timeout triggers retry — mock raises Exception first time, succeeds second
4. Two consecutive timeouts raise ClientError
5. kill_session(id) calls remove on the session object and verifies it's gone
6. connect() when restpy not available raises ClientError

All tests mock SessionAssistant so ixnetwork_restpy is not required.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from ixse.client import ClientError, RestPyClient, SessionDetail, SessionSummary


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_session(session_id: str = "1", name: str = "bgp-test", state: str = "Active") -> MagicMock:
    """Return a MagicMock that mimics a RestPy Session object."""
    s = MagicMock()
    s.Id = session_id
    s.Name = name
    s.State = state
    # Topology is an iterable returning zero topologies by default
    s.Ixnetwork.Topology.find.return_value = []
    # Vport represents port assignments
    s.Ixnetwork.Vport.find.return_value = []
    return s


def _make_mock_assistant(sessions: list[MagicMock] | None = None) -> MagicMock:
    """Return a MagicMock mimicking SessionAssistant.Session.find() result."""
    if sessions is None:
        sessions = [_make_mock_session()]
    assistant = MagicMock()
    assistant.Session.find.return_value = sessions
    return assistant


# ---------------------------------------------------------------------------
# Test 1: list_sessions() returns list[SessionSummary]
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_returns_session_summary_list(self):
        mock_sessions = [
            _make_mock_session("1", "bgp-test", "Active"),
            _make_mock_session("2", "ospf-lab", "InActive"),
        ]
        mock_assistant = _make_mock_assistant(mock_sessions)

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            result = client.list_sessions()

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(s, SessionSummary) for s in result)

    def test_session_summary_fields(self):
        mock_sessions = [_make_mock_session("42", "my-session", "Active")]
        mock_assistant = _make_mock_assistant(mock_sessions)

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            result = client.list_sessions()

        s = result[0]
        assert s.id == "42"
        assert s.name == "my-session"
        assert s.state == "Active"

    def test_empty_server_returns_empty_list(self):
        mock_assistant = _make_mock_assistant([])

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            result = client.list_sessions()

        assert result == []


# ---------------------------------------------------------------------------
# Test 2: get_session(id) returns SessionDetail with correct fields
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_returns_session_detail(self):
        sess = _make_mock_session("7", "topo-test", "Active")
        # Add two topologies
        topo1, topo2 = MagicMock(), MagicMock()
        sess.Ixnetwork.Topology.find.return_value = [topo1, topo2]
        # Two vports (ports)
        vp1, vp2 = MagicMock(), MagicMock()
        vp1.Name = "Ethernet - 001"
        vp1.AssignedTo = "10.0.0.1:1:1"
        vp2.Name = "Ethernet - 002"
        vp2.AssignedTo = "10.0.0.1:1:2"
        sess.Ixnetwork.Vport.find.return_value = [vp1, vp2]

        mock_assistant = _make_mock_assistant([sess])
        mock_assistant.Session.find.return_value = [sess]

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            detail = client.get_session("7")

        assert isinstance(detail, SessionDetail)
        assert detail.id == "7"
        assert detail.name == "topo-test"
        assert detail.topology_count == 2
        assert len(detail.ports) == 2

    def test_get_session_not_found_raises_client_error(self):
        mock_assistant = _make_mock_assistant([])

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            with pytest.raises(ClientError, match="not found"):
                client.get_session("999")

    def test_port_data_is_list_of_dicts(self):
        sess = _make_mock_session("3", "port-test", "Active")
        vp = MagicMock()
        vp.Name = "Ethernet - 001"
        vp.AssignedTo = "10.0.0.1:2:3"
        sess.Ixnetwork.Vport.find.return_value = [vp]
        mock_assistant = _make_mock_assistant([sess])

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
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

        mock_assistant = MagicMock()
        mock_assistant.Session.find.side_effect = flaky_find

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            result = client.list_sessions()

        assert len(result) == 1
        assert call_count == 2  # one failure + one success

    def test_retry_preserves_correct_data(self):
        mock_sessions = [_make_mock_session("5", "retry-session", "Active")]

        attempt = 0

        def flaky_find():
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise TimeoutError("connection timed out")
            return mock_sessions

        mock_assistant = MagicMock()
        mock_assistant.Session.find.side_effect = flaky_find

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            result = client.list_sessions()

        assert result[0].id == "5"
        assert result[0].name == "retry-session"


# ---------------------------------------------------------------------------
# Test 4: Two timeouts raise ClientError
# ---------------------------------------------------------------------------


class TestDoubleTimeoutRaisesClientError:
    def test_two_timeouts_raise_client_error(self):
        mock_assistant = MagicMock()
        mock_assistant.Session.find.side_effect = ConnectionError("timeout every time")

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            with pytest.raises(ClientError):
                client.list_sessions()

    def test_error_message_is_descriptive(self):
        mock_assistant = MagicMock()
        mock_assistant.Session.find.side_effect = TimeoutError("socket timed out")

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            with pytest.raises(ClientError) as exc_info:
                client.list_sessions()

        assert "10.0.0.1" in str(exc_info.value)

    def test_retry_count_is_exactly_two(self):
        """Verify exactly 2 attempts are made (original + 1 retry) before giving up."""
        mock_assistant = MagicMock()
        mock_assistant.Session.find.side_effect = ConnectionError("dead")

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            with pytest.raises(ClientError):
                client.list_sessions()

        assert mock_assistant.Session.find.call_count == 2


# ---------------------------------------------------------------------------
# Test 5: kill_session(id) removes session and verifies it's gone
# ---------------------------------------------------------------------------


class TestKillSession:
    def test_kill_calls_remove_on_session(self):
        sess = _make_mock_session("10", "dead-session", "Active")
        mock_assistant = _make_mock_assistant([sess])
        # After remove, find returns empty (session is gone)
        mock_assistant.Session.find.side_effect = [
            [sess],   # initial find to locate session
            [],       # verification find returns empty
        ]

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            client.kill_session("10")

        sess.remove.assert_called_once()

    def test_kill_nonexistent_session_raises_client_error(self):
        mock_assistant = _make_mock_assistant([])

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            with pytest.raises(ClientError, match="not found"):
                client.kill_session("999")

    def test_kill_verifies_session_gone_after_remove(self):
        sess = _make_mock_session("20", "to-kill", "Active")
        mock_assistant = MagicMock()
        # First call: find the session; second call: verify it's gone
        mock_assistant.Session.find.side_effect = [
            [sess],  # locate session
            [],      # post-remove verification: empty = success
        ]

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            client.kill_session("20")  # must not raise

        assert mock_assistant.Session.find.call_count == 2

    def test_kill_raises_if_session_still_present_after_remove(self):
        sess = _make_mock_session("30", "stubborn", "Active")
        mock_assistant = MagicMock()
        # Session persists after remove (still returned on verification find)
        mock_assistant.Session.find.side_effect = [
            [sess],  # locate session
            [sess],  # verification: still present — kill failed
        ]

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
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
        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant"):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            # Do NOT call connect()
            with pytest.raises(ClientError, match="not connected"):
                client.list_sessions()

    def test_error_message_contains_install_hint(self):
        with patch("ixse.client._RESTPY_AVAILABLE", False):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            with pytest.raises(ClientError) as exc_info:
                client.connect()
        assert "pip install ixnetwork-restpy" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 7: disconnect() is safe to call
# ---------------------------------------------------------------------------


class TestDisconnect:
    def test_disconnect_when_connected(self):
        mock_assistant = _make_mock_assistant()

        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant", return_value=mock_assistant):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.connect()
            client.disconnect()  # must not raise

    def test_disconnect_when_not_connected_is_safe(self):
        with patch("ixse.client._RESTPY_AVAILABLE", True), \
             patch("ixse.client.SessionAssistant"):
            client = RestPyClient("10.0.0.1", "admin", "secret")
            client.disconnect()  # must not raise (idempotent)
