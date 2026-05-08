"""
State management: SQLite persistence + in-memory cache.

Design decisions:
- Single SQLite connection created at init; check_same_thread=False because all
  writes are serialised through a threading.Lock anyway.
- In-memory cache dict {(server, id): Session} provides O(1) reads without
  holding a lock (safe under CPython's GIL for dict reads).
- All mutating operations (upsert, add/remove_tag, delete) acquire the lock
  before touching either the DB or the cache — no partial-write windows.
- On init the cache is warm-loaded from the DB so restarts are transparent to
  read paths.

SQLite schema
-------------
sessions(
    id              TEXT    -- IxNetwork session id
    ixnet_server    TEXT    -- server name from config
    name            TEXT
    ports           TEXT    -- JSON list[SessionPort]
    cp_active       INTEGER -- 0|1
    dp_active       INTEGER -- 0|1
    utilized        INTEGER -- 0|1
    tags            TEXT    -- JSON list[str]
    last_polled_at  TEXT    -- ISO 8601 UTC
    created_at      TEXT    -- ISO 8601 UTC (DB default)
    PRIMARY KEY (id, ixnet_server)
)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from ixse.models import Session, SessionPort


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------


class StateError(Exception):
    """Raised when a requested session does not exist in FleetState."""


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT    NOT NULL,
    ixnet_server    TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    ports           TEXT    NOT NULL,
    cp_active       INTEGER NOT NULL,
    dp_active       INTEGER NOT NULL,
    utilized        INTEGER NOT NULL,
    tags            TEXT    NOT NULL DEFAULT '[]',
    last_polled_at  TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (id, ixnet_server)
);
CREATE INDEX IF NOT EXISTS idx_server      ON sessions(ixnet_server);
CREATE INDEX IF NOT EXISTS idx_last_polled ON sessions(last_polled_at);
"""


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _ports_to_json(ports: list[SessionPort]) -> str:
    return json.dumps([p.model_dump() for p in ports])


def _json_to_ports(raw: str) -> list[SessionPort]:
    return [SessionPort(**d) for d in json.loads(raw)]


def _tags_to_json(tags: list[str]) -> str:
    return json.dumps(tags)


def _json_to_tags(raw: str) -> list[str]:
    return json.loads(raw)


def _dt_to_str(dt: datetime) -> str:
    """Serialise an aware datetime to ISO 8601 UTC string."""
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(raw: str) -> datetime:
    """Deserialise an ISO 8601 string back to a UTC-aware datetime."""
    return datetime.fromisoformat(raw)


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        ixnet_server=row["ixnet_server"],
        name=row["name"],
        ports=_json_to_ports(row["ports"]),
        cp_active=bool(row["cp_active"]),
        dp_active=bool(row["dp_active"]),
        tags=_json_to_tags(row["tags"]),
        last_polled=_str_to_dt(row["last_polled_at"]),
    )


# ---------------------------------------------------------------------------
# FleetState
# ---------------------------------------------------------------------------


class FleetState:
    """Thread-safe SQLite-backed session store with in-memory read cache.

    Usage
    -----
    Instantiate once at application startup:

        state = FleetState(db_path="fleet.db")

    Background poller writes via ``upsert_session``.
    API endpoints read via ``get_session`` / ``get_sessions`` / ``get_all``.
    Call ``close()`` on shutdown.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], Session] = {}

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

        self._warm_cache()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _warm_cache(self) -> None:
        """Populate the in-memory cache from all existing DB rows."""
        cursor = self._conn.execute(
            "SELECT id, ixnet_server, name, ports, cp_active, dp_active, "
            "utilized, tags, last_polled_at FROM sessions"
        )
        for row in cursor.fetchall():
            session = _row_to_session(row)
            self._cache[(session.ixnet_server, session.id)] = session

    def _write_to_db(self, session: Session) -> None:
        """INSERT OR REPLACE the session row. Caller must hold the lock."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sessions
                (id, ixnet_server, name, ports, cp_active, dp_active,
                 utilized, tags, last_polled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.ixnet_server,
                session.name,
                _ports_to_json(session.ports),
                int(session.cp_active),
                int(session.dp_active),
                int(session.utilized),
                _tags_to_json(session.tags),
                _dt_to_str(session.last_polled),
            ),
        )
        self._conn.commit()

    def _update_tags_in_db(self, server: str, session_id: str, tags: list[str]) -> None:
        """Persist an updated tag list. Caller must hold the lock."""
        self._conn.execute(
            "UPDATE sessions SET tags = ? WHERE id = ? AND ixnet_server = ?",
            (_tags_to_json(tags), session_id, server),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert_session(self, session: Session) -> None:
        """Insert or replace a session in both the DB and the cache.

        Thread-safe: serialised through the instance lock.
        """
        with self._lock:
            self._write_to_db(session)
            self._cache[(session.ixnet_server, session.id)] = session

    def get_session(self, server: str, session_id: str) -> Optional[Session]:
        """Return a single session by (server, id) or None if not found.

        Reads from the in-memory cache — no lock needed under CPython's GIL
        for a single dict lookup.
        """
        return self._cache.get((server, session_id))

    def get_sessions(
        self,
        server: Optional[str] = None,
        utilized: Optional[bool] = None,
    ) -> list[Session]:
        """Return sessions, optionally filtered by server and/or utilized flag.

        Reads from in-memory cache; thread-safe under CPython GIL for iteration
        over a stable dict snapshot.
        """
        sessions = list(self._cache.values())

        if server is not None:
            sessions = [s for s in sessions if s.ixnet_server == server]

        if utilized is not None:
            sessions = [s for s in sessions if s.utilized is utilized]

        return sessions

    def get_all(self) -> list[Session]:
        """Return all sessions with no filtering."""
        return list(self._cache.values())

    def add_tag(self, server: str, session_id: str, tag: str) -> Session:
        """Add *tag* to the session identified by (server, session_id).

        Idempotent: if the tag already exists it will not be duplicated.

        Raises
        ------
        StateError
            If the session does not exist.
        """
        with self._lock:
            session = self._cache.get((server, session_id))
            if session is None:
                raise StateError(
                    f"Session '{session_id}' on server '{server}' not found"
                )

            if tag in session.tags:
                return session  # idempotent — nothing to do

            new_tags = list(session.tags) + [tag]
            self._update_tags_in_db(server, session_id, new_tags)

            # Rebuild the Session with the updated tags and refresh cache
            updated = session.model_copy(update={"tags": new_tags})
            self._cache[(server, session_id)] = updated
            return updated

    def remove_tag(self, server: str, session_id: str, tag: str) -> Session:
        """Remove *tag* from the session identified by (server, session_id).

        Idempotent: if the tag does not exist the session is returned unchanged.

        Raises
        ------
        StateError
            If the session does not exist.
        """
        with self._lock:
            session = self._cache.get((server, session_id))
            if session is None:
                raise StateError(
                    f"Session '{session_id}' on server '{server}' not found"
                )

            if tag not in session.tags:
                return session  # idempotent — nothing to do

            new_tags = [t for t in session.tags if t != tag]
            self._update_tags_in_db(server, session_id, new_tags)

            updated = session.model_copy(update={"tags": new_tags})
            self._cache[(server, session_id)] = updated
            return updated

    def delete_session(self, server: str, session_id: str) -> None:
        """Remove the session from DB and cache.

        Raises
        ------
        StateError
            If the session does not exist.
        """
        with self._lock:
            if (server, session_id) not in self._cache:
                raise StateError(
                    f"Session '{session_id}' on server '{server}' not found"
                )

            self._conn.execute(
                "DELETE FROM sessions WHERE id = ? AND ixnet_server = ?",
                (session_id, server),
            )
            self._conn.commit()
            del self._cache[(server, session_id)]

    def close(self) -> None:
        """Close the SQLite connection. Call on application shutdown."""
        self._conn.close()
