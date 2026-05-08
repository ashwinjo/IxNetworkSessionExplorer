"""
Unit tests for ixse/ixos.py — IxOS REST client.

TDD — written before the implementation.
Coverage:
  1. Successful port stats returned correctly
  2. Timeout triggers retry (mock raises Timeout first, succeeds second)
  3. Two consecutive timeouts → IxOSClientError raised
  4. 401 response → IxOSClientError immediately (no retry)
  5. 404 response → IxOSClientError with card/port info
  6. Malformed JSON → IxOSClientError
"""

from unittest.mock import MagicMock, patch, call
import pytest
import requests

from ixse.ixos import IxOSClient, IxOSClientError, PortStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHASSIS_HOST = "10.1.1.1"
USERNAME = "admin"
PASSWORD = "secret"
CARD = 2
PORT = 4

GOOD_RESPONSE_JSON = {
    "txFrames": 1234567,
    "rxFrames": 890123,
    "portState": "up",
}


def make_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON object could be decoded")
    return resp


def make_client() -> IxOSClient:
    return IxOSClient(CHASSIS_HOST, USERNAME, PASSWORD)


# ---------------------------------------------------------------------------
# 1. Successful port stats returned correctly
# ---------------------------------------------------------------------------


class TestGetPortStatsSuccess:
    def test_fields_mapped_correctly(self):
        client = make_client()
        mock_resp = make_response(200, GOOD_RESPONSE_JSON)

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            stats = client.get_port_stats(CARD, PORT)

        assert isinstance(stats, PortStats)
        assert stats.tx_frames == 1234567
        assert stats.rx_frames == 890123
        assert stats.port_state == "up"

    def test_correct_url_constructed(self):
        client = make_client()
        mock_resp = make_response(200, GOOD_RESPONSE_JSON)

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.get_port_stats(3, 7)

        expected_url = f"http://{CHASSIS_HOST}/api/v1/ixos/ports/3/7/stats"
        mock_get.assert_called_once_with(expected_url, timeout=10)

    def test_port_state_down(self):
        client = make_client()
        mock_resp = make_response(200, {"txFrames": 0, "rxFrames": 0, "portState": "down"})

        with patch.object(client._session, "get", return_value=mock_resp):
            stats = client.get_port_stats(1, 1)

        assert stats.port_state == "down"
        assert stats.tx_frames == 0
        assert stats.rx_frames == 0

    def test_zero_frame_counts_valid(self):
        client = make_client()
        mock_resp = make_response(200, {"txFrames": 0, "rxFrames": 0, "portState": "up"})

        with patch.object(client._session, "get", return_value=mock_resp):
            stats = client.get_port_stats(1, 1)

        assert stats.tx_frames == 0
        assert stats.rx_frames == 0


# ---------------------------------------------------------------------------
# 2. Timeout triggers retry (first call raises Timeout, second succeeds)
# ---------------------------------------------------------------------------


class TestRetryOnTimeout:
    def test_single_timeout_then_success(self):
        client = make_client()
        mock_resp = make_response(200, GOOD_RESPONSE_JSON)

        with patch.object(
            client._session,
            "get",
            side_effect=[requests.exceptions.Timeout(), mock_resp],
        ) as mock_get:
            stats = client.get_port_stats(CARD, PORT)

        assert stats.tx_frames == 1234567
        assert mock_get.call_count == 2

    def test_single_connection_error_then_success(self):
        client = make_client()
        mock_resp = make_response(200, GOOD_RESPONSE_JSON)

        with patch.object(
            client._session,
            "get",
            side_effect=[requests.exceptions.ConnectionError("refused"), mock_resp],
        ) as mock_get:
            stats = client.get_port_stats(CARD, PORT)

        assert stats.tx_frames == 1234567
        assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# 3. Two consecutive timeouts → IxOSClientError
# ---------------------------------------------------------------------------


class TestDoubleTimeoutRaises:
    def test_two_timeouts_raise_client_error(self):
        client = make_client()

        with patch.object(
            client._session,
            "get",
            side_effect=[
                requests.exceptions.Timeout(),
                requests.exceptions.Timeout(),
            ],
        ) as mock_get:
            with pytest.raises(IxOSClientError) as exc_info:
                client.get_port_stats(CARD, PORT)

        assert mock_get.call_count == 2
        assert "timeout" in str(exc_info.value).lower()

    def test_two_connection_errors_raise_client_error(self):
        client = make_client()

        with patch.object(
            client._session,
            "get",
            side_effect=[
                requests.exceptions.ConnectionError("eof"),
                requests.exceptions.ConnectionError("eof"),
            ],
        ) as mock_get:
            with pytest.raises(IxOSClientError):
                client.get_port_stats(CARD, PORT)

        assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# 4. 401/403 response → IxOSClientError immediately (no retry)
# ---------------------------------------------------------------------------


class TestAuthFailureNoRetry:
    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error_raises_immediately(self, status_code: int):
        client = make_client()
        mock_resp = make_response(status_code, text="Unauthorized")

        with patch.object(
            client._session, "get", return_value=mock_resp
        ) as mock_get:
            with pytest.raises(IxOSClientError) as exc_info:
                client.get_port_stats(CARD, PORT)

        # Must not retry — exactly 1 call
        assert mock_get.call_count == 1
        assert str(status_code) in str(exc_info.value)

    def test_401_error_message_mentions_auth(self):
        client = make_client()
        mock_resp = make_response(401, text="Unauthorized")

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(IxOSClientError) as exc_info:
                client.get_port_stats(CARD, PORT)

        error_msg = str(exc_info.value).lower()
        assert "auth" in error_msg or "401" in error_msg or "unauthorized" in error_msg


# ---------------------------------------------------------------------------
# 5. 404 response → IxOSClientError with card/port info
# ---------------------------------------------------------------------------


class TestPortNotFound:
    def test_404_raises_with_port_info(self):
        client = make_client()
        mock_resp = make_response(404, text="Not Found")

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(IxOSClientError) as exc_info:
                client.get_port_stats(CARD, PORT)

        error_msg = str(exc_info.value)
        assert str(CARD) in error_msg
        assert str(PORT) in error_msg

    def test_404_error_message_format(self):
        client = make_client()
        mock_resp = make_response(404, text="Not Found")

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(IxOSClientError) as exc_info:
                client.get_port_stats(5, 12)

        assert "5" in str(exc_info.value)
        assert "12" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. Malformed JSON → IxOSClientError
# ---------------------------------------------------------------------------


class TestMalformedJsonResponse:
    def test_invalid_json_body_raises(self):
        client = make_client()
        # json() raises ValueError to simulate bad JSON
        mock_resp = make_response(200, json_data=None, text="not-json-at-all")

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(IxOSClientError) as exc_info:
                client.get_port_stats(CARD, PORT)

        assert "parse" in str(exc_info.value).lower() or "json" in str(exc_info.value).lower()

    def test_missing_tx_frames_key_raises(self):
        client = make_client()
        # Valid JSON but missing required keys
        mock_resp = make_response(200, {"portState": "up"})

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(IxOSClientError):
                client.get_port_stats(CARD, PORT)

    def test_wrong_type_for_tx_frames_raises(self):
        client = make_client()
        mock_resp = make_response(200, {"txFrames": "not-an-int", "rxFrames": 0, "portState": "up"})

        with patch.object(client._session, "get", return_value=mock_resp):
            with pytest.raises(IxOSClientError):
                client.get_port_stats(CARD, PORT)


# ---------------------------------------------------------------------------
# Session / auth setup
# ---------------------------------------------------------------------------


class TestSessionSetup:
    def test_session_auth_set_on_init(self):
        client = IxOSClient(CHASSIS_HOST, USERNAME, PASSWORD)
        assert client._session.auth == (USERNAME, PASSWORD)

    def test_different_clients_have_independent_sessions(self):
        c1 = IxOSClient("10.1.1.1", "admin", "pass1")
        c2 = IxOSClient("10.1.1.2", "admin", "pass2")
        assert c1._session is not c2._session
        assert c1._session.auth != c2._session.auth
