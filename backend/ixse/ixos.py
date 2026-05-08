"""
IxOS REST API abstraction: chassis port statistics client.

Provides methods to query port TX/RX frame counters for data plane
(DP) traffic detection via IxOS REST endpoints.

Endpoint pattern: http://{chassis_host}/api/v1/ixos/ports/{card}/{port}/stats
"""

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


class IxOSClientError(Exception):
    """Raised on any IxOS REST API failure (auth, network, parse, not-found)."""


@dataclass
class PortStats:
    """Port statistics from IxOS REST API."""

    tx_frames: int
    rx_frames: int
    port_state: str  # "up", "down", "unknown"


class IxOSClient:
    """
    IxOS REST API client for port statistics.

    Wraps requests.Session for connection reuse and basic auth across calls.
    Retries once on transient network errors (Timeout, ConnectionError).
    Does NOT retry on auth failures (401/403) or missing resources (404).
    """

    _MAX_RETRIES = 1  # one retry = two total attempts
    _TIMEOUT = 10  # seconds

    def __init__(self, chassis_host: str, username: str, password: str) -> None:
        """
        Initialize IxOS client.

        Args:
            chassis_host: IxOS chassis IP or hostname.
            username: Basic auth username.
            password: Basic auth password.
        """
        self.chassis_host = chassis_host
        self._session = requests.Session()
        self._session.auth = (username, password)

    def get_port_stats(self, card: int, port: int) -> PortStats:
        """
        Query IxOS REST for port TX/RX frame counts.

        Args:
            card: Card number (1-indexed).
            port: Port number (1-indexed).

        Returns:
            PortStats with tx_frames, rx_frames, port_state.

        Raises:
            IxOSClientError: On timeout (after 1 retry), auth failure,
                             port not found, or response parse error.
        """
        url = f"http://{self.chassis_host}/api/v1/ixos/ports/{card}/{port}/stats"
        last_exc: Exception | None = None

        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = self._session.get(url, timeout=self._TIMEOUT)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    logger.warning(
                        "IxOS transient error on %s (attempt %d/%d): %s — retrying",
                        url,
                        attempt + 1,
                        self._MAX_RETRIES + 1,
                        exc,
                    )
                    continue
                # Exhausted retries
                raise IxOSClientError(
                    f"IxOS request to {url} failed after {self._MAX_RETRIES + 1} "
                    f"attempts due to timeout/connection error: {exc}"
                ) from exc

            # Auth failures: raise immediately, no retry
            if response.status_code in (401, 403):
                raise IxOSClientError(
                    f"IxOS auth failure (HTTP {response.status_code}) for "
                    f"{self.chassis_host} — check credentials"
                )

            # Port not found
            if response.status_code == 404:
                raise IxOSClientError(f"Port {card}/{port} not found on {self.chassis_host}")

            # Any other non-2xx
            if response.status_code >= 400:
                raise IxOSClientError(
                    f"IxOS returned HTTP {response.status_code} for {url}: {response.text!r}"
                )

            return self._parse_port_stats(response, card, port)

        # Should be unreachable — satisfies type checker
        assert last_exc is not None
        raise IxOSClientError(
            f"IxOS request to {url} failed: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_port_stats(
        self, response: requests.Response, card: int, port: int
    ) -> PortStats:
        """
        Parse an IxOS port stats JSON response into PortStats.

        Expected payload:
            {"txFrames": int, "rxFrames": int, "portState": str}

        Raises:
            IxOSClientError: On JSON decode failure or missing/wrong-type fields.
        """
        try:
            data = response.json()
        except ValueError as exc:
            raise IxOSClientError(
                f"Failed to parse JSON response from IxOS port {card}/{port}: "
                f"raw={response.text!r}"
            ) from exc

        try:
            tx_frames = data["txFrames"]
            rx_frames = data["rxFrames"]
            port_state = data["portState"]
        except KeyError as exc:
            raise IxOSClientError(
                f"Missing field {exc} in IxOS response for port {card}/{port}: {data!r}"
            ) from exc

        # Enforce integer types for frame counters
        if not isinstance(tx_frames, int):
            raise IxOSClientError(
                f"IxOS returned non-integer txFrames={tx_frames!r} for port {card}/{port}"
            )
        if not isinstance(rx_frames, int):
            raise IxOSClientError(
                f"IxOS returned non-integer rxFrames={rx_frames!r} for port {card}/{port}"
            )

        return PortStats(
            tx_frames=tx_frames,
            rx_frames=rx_frames,
            port_state=str(port_state),
        )
