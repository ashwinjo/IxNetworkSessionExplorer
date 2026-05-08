"""
RestPy abstraction: IxNetwork API client using TestPlatform.

Uses TestPlatform + Sessions.find() to enumerate EXISTING sessions on
a Linux API Server.  No new sessions are ever created — this is a
read/inspect/kill-only client.

Import guard: ixnetwork_restpy is optional at import time so that tests
and non-IxNetwork environments can import this module without the library
installed.  connect() will raise ClientError if unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from ixse.models import LldpPeerInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional import guard
# ---------------------------------------------------------------------------

try:
    from ixnetwork_restpy.testplatform.testplatform import TestPlatform  # type: ignore[import-untyped]

    _RESTPY_AVAILABLE = True
except ImportError:
    _RESTPY_AVAILABLE = False
    TestPlatform = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ClientError(Exception):
    """Raised for all RestPy client failures."""


# ---------------------------------------------------------------------------
# Transport-layer DTOs
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """Lightweight session descriptor returned by list_sessions()."""

    id: str
    name: str
    state: str  # e.g. "Active", "stopped"


class SessionDetail(BaseModel):
    """Full session descriptor returned by get_session()."""

    id: str
    name: str
    ports: list[dict[str, Any]]  # raw vport data; mapped to SessionPort by plane.py
    topology_count: int


# ---------------------------------------------------------------------------
# Internal retry helper
# ---------------------------------------------------------------------------

_MAX_RETRIES = 1


def _with_retry(fn: Any, host: str) -> Any:
    """Execute *fn* with one retry on transient errors.

    Auth errors (PermissionError, ValueError) are re-raised immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except (PermissionError, ValueError) as exc:
            raise ClientError(f"Non-retryable error from {host}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Transient error from %s (attempt %d/%d): %s — retrying",
                    host, attempt + 1, _MAX_RETRIES + 1, exc,
                )
            else:
                logger.error(
                    "Permanent error from %s after %d attempts: %s",
                    host, _MAX_RETRIES + 1, exc,
                )
    raise ClientError(
        f"Failed to communicate with {host} after {_MAX_RETRIES + 1} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# LLDP helpers
# ---------------------------------------------------------------------------


def _parse_location_str(raw: str) -> tuple[str, int, int] | None:
    """Parse a port Location string into (chassis_ip, card, port).

    Handles all three formats:
      - "10.36.236.121;6;3"  (semicolon — preferred, Location field)
      - "10.36.236.121:6:3"  (colon — AssignedTo field)
      - "//10.36.236.121/6/3" (slash — legacy)

    Returns None when the string is empty or unparseable.
    """
    raw = raw.strip()
    if not raw:
        return None
    for sep in (";", ":", "/"):
        parts = [p for p in raw.split(sep) if p]
        if len(parts) >= 3:
            try:
                return parts[0], int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                continue
    return None


def fetch_lldp_map(ixnetwork_obj: Any) -> dict[tuple[str, int, int], LldpPeerInfo]:
    """Query IxNetwork Locations API and return per-port LLDP neighbor info.

    Walks ``ixnetwork_obj.Locations.find()`` → ``location.Ports.find()`` and
    reads all ``Peer*`` attributes from each port object.  Ports whose Location
    string cannot be parsed are silently skipped.

    Args:
        ixnetwork_obj: RestPy IxNetwork handle (duck-typed; accepts mock).

    Returns:
        Mapping of (chassis_ip, card, port) → LldpPeerInfo.
        Empty dict on any top-level failure so callers can safely fall through.
    """
    result: dict[tuple[str, int, int], LldpPeerInfo] = {}
    try:
        locations = ixnetwork_obj.Locations.find()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch IxNetwork Locations for LLDP: %s", exc)
        return result

    for loc in locations:
        try:
            ports = loc.Ports.find()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch Ports for location %s: %s", loc, exc)
            continue

        for port_obj in ports:
            location_str = str(getattr(port_obj, "Location", "") or "")
            parsed = _parse_location_str(location_str)
            if parsed is None:
                continue
            chassis_ip, card, port_num = parsed

            def _safe_str(attr: str) -> str:
                return str(getattr(port_obj, attr, "") or "")

            def _safe_int(attr: str) -> int:
                raw = getattr(port_obj, attr, 0)
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return 0

            lldp = LldpPeerInfo(
                peer_chassis_id=_safe_str("PeerChassisId"),
                peer_description=_safe_str("PeerDescription"),
                peer_hold_time=_safe_int("PeerHoldTime"),
                peer_ip_address=_safe_str("PeerIpAddress"),
                peer_port_id=_safe_str("PeerPortId"),
                peer_system_name=_safe_str("PeerSystemName"),
                peer_system_description=_safe_str("PeerSystemDescription"),
            )
            result[(chassis_ip, card, port_num)] = lldp
            logger.debug(
                "LLDP: %s/%d/%d → peer=%s",
                chassis_ip, card, port_num, lldp.peer_system_name or "(none)",
            )

    return result


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RestPyClient:
    """IxNetwork client using TestPlatform for read-only session enumeration.

    Connects to an existing Linux API Server and lists all sessions that are
    already running — never creates a new session.

    Lifecycle::

        client = RestPyClient(host, username, password, rest_port=443)
        client.connect()
        sessions = client.list_sessions()
        raw = client.get_raw_sessions()   # for CP detection
        client.disconnect()
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        rest_port: int | None = None,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.rest_port = rest_port
        self._platform: Any | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Authenticate with the IxNetwork Linux API Server.

        Uses TestPlatform.Authenticate() — no session is created.

        Raises:
            ClientError: If ixnetwork_restpy is not installed, or if
                         authentication fails.
        """
        if not _RESTPY_AVAILABLE:
            raise ClientError(
                "ixnetwork_restpy is not installed. "
                "Install with: pip install ixnetwork-restpy"
            )
        try:
            kwargs: dict[str, Any] = {
                "ip_address": self.host,
                "verify_cert": False,
            }
            if self.rest_port is not None:
                kwargs["rest_port"] = self.rest_port

            platform = TestPlatform(**kwargs)
            platform.Authenticate(self.username, self.password)
            self._platform = platform
            logger.info("Connected to IxNetwork server %s", self.host)
        except Exception as exc:
            raise ClientError(
                f"Failed to connect to IxNetwork server {self.host}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Release the TestPlatform handle. Safe to call when not connected."""
        if self._platform is not None:
            self._platform = None
            logger.info("Disconnected from IxNetwork server %s", self.host)

    def _require_connected(self) -> Any:
        if self._platform is None:
            raise ClientError(
                f"RestPyClient for {self.host} is not connected. "
                "Call connect() first."
            )
        return self._platform

    # ------------------------------------------------------------------
    # Session queries
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[SessionSummary]:
        """List all existing sessions on this IxNetwork server.

        Does NOT create any new sessions.

        Returns:
            List of SessionSummary DTOs (one per existing session).
        """
        platform = self._require_connected()

        def _fetch() -> list[SessionSummary]:
            raw = platform.Sessions.find()
            return [
                SessionSummary(
                    id=str(s.Id),
                    name=str(s.Name),
                    state=str(getattr(s, "State", "unknown")),
                )
                for s in raw
            ]

        return _with_retry(_fetch, self.host)

    def get_raw_sessions(self) -> list[Any]:
        """Return raw RestPy Session objects for CP detection and port mapping.

        Each object exposes:
          - ``.Id``        — session ID string
          - ``.Name``      — session name
          - ``.State``     — session state
          - ``.Ixnetwork`` — IxNetwork handle (has ``.Topology``, ``.Vport``)

        Does NOT create any new sessions.
        """
        platform = self._require_connected()

        def _fetch() -> list[Any]:
            return list(platform.Sessions.find())

        return _with_retry(_fetch, self.host)

    def get_session(self, session_id: str) -> SessionDetail:
        """Get full session detail for a specific existing session.

        Raises:
            ClientError: If session not found, or on transport failure.
        """
        platform = self._require_connected()

        def _fetch() -> SessionDetail:
            raw_sessions = platform.Sessions.find()
            matched = [s for s in raw_sessions if str(s.Id) == session_id]
            if not matched:
                raise ClientError(
                    f"Session {session_id!r} not found on server {self.host}"
                )
            sess = matched[0]
            ixnetwork = sess.Ixnetwork
            topologies = ixnetwork.Topology.find()
            vports = ixnetwork.Vport.find()
            ports = [
                {
                    "name": str(vp.Name),
                    "assigned_to": str(getattr(vp, "AssignedTo", "")),
                }
                for vp in vports
            ]
            return SessionDetail(
                id=str(sess.Id),
                name=str(sess.Name),
                ports=ports,
                topology_count=len(topologies),
            )

        try:
            return _with_retry(_fetch, self.host)
        except ClientError:
            raise

    def collect_logs_to_file(self, session_id: str, output_dir: str) -> str:
        """Collect diagnostic logs for a session and download the zip to *output_dir*.

        Calls ``IxNetwork.CollectLogs`` to bundle all diagnostics on the server,
        then downloads the resulting ``diagnostic_logs.zip`` into *output_dir*.

        Args:
            session_id: The numeric session ID string.
            output_dir:  Local directory path to download the zip into.

        Returns:
            Absolute path to the downloaded zip file.

        Raises:
            ClientError: If the session is not found or collection fails.
        """
        if not _RESTPY_AVAILABLE:
            raise ClientError(
                "ixnetwork_restpy is not installed. "
                "Install with: pip install ixnetwork-restpy"
            )

        platform = self._require_connected()

        raw_sessions = platform.Sessions.find()
        matched = [s for s in raw_sessions if str(s.Id) == session_id]
        if not matched:
            raise ClientError(
                f"Session {session_id!r} not found on server {self.host} — "
                "cannot collect logs for a session that does not exist"
            )

        sess = matched[0]
        ixnetwork = sess.Ixnetwork

        try:
            from ixnetwork_restpy import Files  # type: ignore[import-untyped]

            logger.info(
                "Collecting diagnostic logs for session %r on %s", session_id, self.host
            )
            ixnetwork.CollectLogs(Arg1=Files("diagnostic_logs"), Arg2="currentInstance")
            sess.DownloadFile("diagnostic_logs.zip", output_dir)
        except Exception as exc:
            raise ClientError(
                f"Failed to collect logs for session {session_id!r} on {self.host}: {exc}"
            ) from exc

        import os
        local_path = os.path.join(output_dir, "diagnostic_logs.zip")
        logger.info(
            "Diagnostic logs for session %r downloaded to %s", session_id, local_path
        )
        return local_path

    def kill_session(self, session_id: str) -> None:
        """Remove an existing session and verify it is gone.

        Raises:
            ClientError: If session not found, remove fails, or session
                         is still present after removal.
        """
        platform = self._require_connected()

        raw_sessions = platform.Sessions.find()
        matched = [s for s in raw_sessions if str(s.Id) == session_id]
        if not matched:
            raise ClientError(
                f"Session {session_id!r} not found on server {self.host} — "
                "cannot kill a session that does not exist"
            )

        try:
            matched[0].remove()
        except Exception as exc:
            raise ClientError(
                f"Failed to remove session {session_id!r} from {self.host}: {exc}"
            ) from exc

        remaining = platform.Sessions.find()
        if any(str(s.Id) == session_id for s in remaining):
            raise ClientError(
                f"Session {session_id!r} on {self.host} still present after kill"
            )

        logger.info("Session %r killed on %s", session_id, self.host)
