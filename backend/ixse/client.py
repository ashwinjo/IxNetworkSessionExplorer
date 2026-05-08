"""
RestPy abstraction: IxNetwork API client wrapper.

Provides Control Plane (CP) session discovery, topology queries,
and session lifecycle management via ixnetwork-restpy.

Import guard: ixnetwork_restpy is optional at import time so that
tests and non-IxNetwork environments can import this module without
the library installed. connect() will raise ClientError if unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import guard — allows unit tests to run without the library
# ---------------------------------------------------------------------------

try:
    from ixnetwork_restpy import SessionAssistant  # type: ignore[import-untyped]

    _RESTPY_AVAILABLE = True
except ImportError:
    _RESTPY_AVAILABLE = False
    SessionAssistant = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ClientError(Exception):
    """Raised for all RestPy client failures.

    Distinguishes:
    - Auth failures (no retry)
    - Transport/timeout failures (retried once)
    - State errors (session not found, kill verification failed)
    - Dependency errors (restpy not installed)
    """


# ---------------------------------------------------------------------------
# Transport-layer DTOs (not in models.py — these are RestPy-specific)
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """Lightweight session descriptor returned by list_sessions()."""

    id: str
    name: str
    state: str  # e.g. "Active", "InActive"


class SessionDetail(BaseModel):
    """Full session descriptor returned by get_session()."""

    id: str
    name: str
    ports: list[dict[str, Any]]  # raw vport data; mapped to SessionPort by plane.py
    topology_count: int


# ---------------------------------------------------------------------------
# Internal retry helper
# ---------------------------------------------------------------------------

_MAX_RETRIES = 1  # one retry → two total attempts


def _with_retry(fn: Any, host: str) -> Any:
    """Execute *fn* with one retry on transient errors.

    Auth errors (PermissionError, ValueError containing "auth") are re-raised
    immediately without retry.

    Args:
        fn: Zero-argument callable to execute.
        host: IxNetwork server hostname (for error context in ClientError).

    Returns:
        Whatever *fn* returns on success.

    Raises:
        ClientError: After two consecutive failures, wrapping the last exception.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except (PermissionError, ValueError) as exc:
            # Auth / bad-argument errors — no point retrying
            raise ClientError(f"Non-retryable error from {host}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Transient error from %s (attempt %d/%d): %s — retrying",
                    host,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    exc,
                )
            else:
                logger.error(
                    "Permanent error from %s after %d attempts: %s",
                    host,
                    _MAX_RETRIES + 1,
                    exc,
                )

    raise ClientError(
        f"Failed to communicate with IxNetwork server {host} after "
        f"{_MAX_RETRIES + 1} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RestPyClient:
    """IxNetwork RestPy client. Provides CP session discovery.

    Lifecycle:
        client = RestPyClient(host, username, password)
        client.connect()
        sessions = client.list_sessions()
        ...
        client.disconnect()

    connect() must be called before any query method. Not thread-safe on its
    own — the caller (background poller) is responsible for synchronisation.
    """

    def __init__(self, host: str, username: str, password: str, rest_port: int | None = None) -> None:
        """Store connection parameters. Does not connect (lazy connect pattern).

        Args:
            host: IxNetwork server IP or hostname.
            username: Authentication username.
            password: Authentication password.
            rest_port: REST API port. None lets RestPy auto-detect (tries 11009
                       then 443). Use 443 for HTTPS-only servers.
        """
        self.host = host
        self.username = username
        self.password = password
        self.rest_port = rest_port
        self._assistant: Any | None = None  # set by connect()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the IxNetwork server.

        Raises:
            ClientError: If ixnetwork_restpy is not installed, or if the
                         connection attempt fails.
        """
        if not _RESTPY_AVAILABLE:
            raise ClientError(
                "ixnetwork_restpy is not installed. "
                "Install with: pip install ixnetwork-restpy"
            )

        try:
            kwargs: dict[str, Any] = dict(
                IpAddress=self.host,
                UserName=self.username,
                Password=self.password,
                LogLevel="warning",
            )
            if self.rest_port is not None:
                kwargs["RestPort"] = self.rest_port

            self._assistant = SessionAssistant(**kwargs)
            logger.info("Connected to IxNetwork server %s", self.host)
        except Exception as exc:
            raise ClientError(
                f"Failed to connect to IxNetwork server {self.host}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Disconnect cleanly. Safe to call even if not connected (idempotent)."""
        if self._assistant is None:
            return
        try:
            # SessionAssistant does not expose an explicit disconnect; releasing
            # the reference is sufficient for non-persistent sessions.
            self._assistant = None
            logger.info("Disconnected from IxNetwork server %s", self.host)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during disconnect from %s: %s", self.host, exc)
            self._assistant = None

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _require_connected(self) -> Any:
        """Return the SessionAssistant or raise ClientError if not connected."""
        if self._assistant is None:
            raise ClientError(
                f"RestPyClient for {self.host} is not connected. "
                "Call connect() first."
            )
        return self._assistant

    # ------------------------------------------------------------------
    # Session queries
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[SessionSummary]:
        """List all sessions on this IxNetwork server.

        Returns:
            List of SessionSummary DTOs (one per session).

        Raises:
            ClientError: On connection failure after retry, or if not connected.
        """
        assistant = self._require_connected()

        def _fetch() -> list[SessionSummary]:
            raw_sessions = assistant.Session.find()
            return [
                SessionSummary(
                    id=str(s.Id),
                    name=str(s.Name),
                    state=str(s.State),
                )
                for s in raw_sessions
            ]

        return _with_retry(_fetch, self.host)

    def get_session(self, session_id: str) -> SessionDetail:
        """Get full session detail for a specific session.

        Args:
            session_id: The session ID (as a string) to look up.

        Returns:
            SessionDetail DTO with port and topology data.

        Raises:
            ClientError: If session not found, or on transport failure.
        """
        assistant = self._require_connected()

        def _fetch() -> SessionDetail:
            raw_sessions = assistant.Session.find()
            matched = [s for s in raw_sessions if str(s.Id) == session_id]
            if not matched:
                raise ClientError(
                    f"Session {session_id!r} not found on server {self.host}"
                )
            sess = matched[0]

            topologies = sess.Ixnetwork.Topology.find()
            vports = sess.Ixnetwork.Vport.find()

            ports = [
                {
                    "name": str(vp.Name),
                    "assigned_to": str(vp.AssignedTo),
                }
                for vp in vports
            ]

            return SessionDetail(
                id=str(sess.Id),
                name=str(sess.Name),
                ports=ports,
                topology_count=len(topologies),
            )

        # ClientError (not found) should propagate immediately, not be retried
        try:
            return _with_retry(_fetch, self.host)
        except ClientError:
            raise

    def kill_session(self, session_id: str) -> None:
        """Remove a session from IxNetwork and verify it is gone.

        Args:
            session_id: The session ID to kill.

        Raises:
            ClientError: If session not found, remove call fails, or the
                         session is still present after remove (kill failed).
        """
        assistant = self._require_connected()

        # Locate session
        raw_sessions = assistant.Session.find()
        matched = [s for s in raw_sessions if str(s.Id) == session_id]
        if not matched:
            raise ClientError(
                f"Session {session_id!r} not found on server {self.host} — "
                "cannot kill a session that does not exist"
            )

        sess = matched[0]
        try:
            sess.remove()
        except Exception as exc:
            raise ClientError(
                f"Failed to remove session {session_id!r} from {self.host}: {exc}"
            ) from exc

        # Verify the session is gone
        remaining = assistant.Session.find()
        still_present = [s for s in remaining if str(s.Id) == session_id]
        if still_present:
            raise ClientError(
                f"Session {session_id!r} on {self.host} is still present after "
                "kill — remove may have failed silently"
            )

        logger.info("Session %r killed on %s", session_id, self.host)
