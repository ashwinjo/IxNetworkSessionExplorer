"""
IxOS REST API abstraction: chassis port statistics client.

Provides methods to query port TX/RX frame counters for data plane
(DP) traffic detection via IxOS REST endpoints.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PortStats:
    """Port statistics from IxOS REST API."""
    tx_frames: int
    rx_frames: int
    port_state: str  # "up", "down", etc.


class IxOSClient:
    """
    IxOS REST API client for port statistics.

    Handles authentication and queries to IxOS chassis REST endpoints
    for data plane traffic detection.
    """

    def __init__(self, host: str, username: str, password: str):
        """
        Initialize IxOS client.

        Args:
            host: IxOS chassis IP/hostname
            username: Authentication username
            password: Authentication password
        """
        self.host = host
        self.username = username
        self.password = password

    def connect(self) -> None:
        """Establish connection to IxOS chassis."""
        pass

    def get_port_stats(self, card: int, port: int) -> PortStats:
        """
        Get TX/RX frame counters for a specific port.

        Args:
            card: Card number
            port: Port number

        Returns:
            PortStats with tx_frames, rx_frames, and port state.
        """
        pass

    def get_all_port_stats(self) -> dict[tuple[int, int], PortStats]:
        """Get stats for all ports on chassis."""
        pass

    def disconnect(self) -> None:
        """Close connection."""
        pass
