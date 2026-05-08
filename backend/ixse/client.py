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
