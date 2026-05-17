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

from ixse.models import KcosInfo, ServerEntry, Session, SessionPort


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------


class StateError(Exception):
    """Raised when a requested session does not exist in FleetState."""


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS servers (
    name        TEXT    PRIMARY KEY,
    host        TEXT    NOT NULL,
    username    TEXT    NOT NULL,
    password    TEXT    NOT NULL DEFAULT '',
    rest_port   INTEGER,
    tags        TEXT    NOT NULL DEFAULT '[]',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT    NOT NULL,
    ixnet_server    TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    username        TEXT    NOT NULL DEFAULT '',
    ports           TEXT    NOT NULL,
    cp_active       INTEGER NOT NULL DEFAULT 0,
    dp_active       INTEGER NOT NULL DEFAULT 0,
    utilized        INTEGER NOT NULL DEFAULT 0,
    tags            TEXT    NOT NULL DEFAULT '[]',
    last_polled_at  TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    session_state   TEXT    NOT NULL DEFAULT '',
    error_status    TEXT    NOT NULL DEFAULT 'NOERROR',
    error_count     INTEGER NOT NULL DEFAULT 0,
    error_list      TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (id, ixnet_server)
);
CREATE INDEX IF NOT EXISTS idx_server      ON sessions(ixnet_server);
CREATE INDEX IF NOT EXISTS idx_last_polled ON sessions(last_polled_at);

CREATE TABLE IF NOT EXISTS kcos_cache (
    host      TEXT PRIMARY KEY,
    kcos_info TEXT NOT NULL,
    probed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
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
    # cp_active / dp_active / utilized are derived by the Session model_validator
    # from the per-port data stored in the ports JSON — no need to read the
    # denormalised session-level columns here.
    keys = row.keys()
    return Session(
        id=row["id"],
        ixnet_server=row["ixnet_server"],
        name=row["name"],
        username=row["username"] if "username" in keys else "",
        ports=_json_to_ports(row["ports"]),
        tags=_json_to_tags(row["tags"]),
        last_polled=_str_to_dt(row["last_polled_at"]),
        session_state=row["session_state"] if "session_state" in keys else "",
        error_status=row["error_status"] if "error_status" in keys else "NOERROR",
        error_count=int(row["error_count"]) if "error_count" in keys else 0,
        error_list=json.loads(row["error_list"]) if "error_list" in keys else [],
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
        self._migrate()
        self._purge_orphaned_sessions()
        self._warm_cache()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        """Apply additive schema migrations for existing databases.

        Each ALTER TABLE is attempted individually so that a partially-migrated
        database (e.g. after an interrupted upgrade) still ends up fully
        migrated.  OperationalError means the column already exists — safe
        to ignore.
        """
        migrations = [
            "ALTER TABLE servers   ADD COLUMN tags          TEXT    NOT NULL DEFAULT '[]'",
            "ALTER TABLE sessions  ADD COLUMN username      TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE sessions  ADD COLUMN session_state TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE sessions  ADD COLUMN error_status  TEXT    NOT NULL DEFAULT 'NOERROR'",
            "ALTER TABLE sessions  ADD COLUMN error_count   INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sessions  ADD COLUMN error_list    TEXT    NOT NULL DEFAULT '[]'",
            "ALTER TABLE servers   ADD COLUMN kcos_info     TEXT",
        ]
        for sql in migrations:
            try:
                self._conn.execute(sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists — nothing to do

    def _purge_orphaned_sessions(self) -> None:
        """Delete sessions whose server no longer exists in the servers table.

        Runs at startup before the cache is warmed so stale rows from
        previously deleted servers never surface in API responses.
        """
        self._conn.execute(
            "DELETE FROM sessions WHERE ixnet_server NOT IN (SELECT name FROM servers)"
        )
        self._conn.commit()

    def _warm_cache(self) -> None:
        """Populate the in-memory cache from all existing DB rows."""
        cursor = self._conn.execute(
            "SELECT id, ixnet_server, name, username, ports, cp_active, dp_active, "
            "utilized, tags, last_polled_at, session_state, error_status, "
            "error_count, error_list FROM sessions"
        )
        for row in cursor.fetchall():
            session = _row_to_session(row)
            self._cache[(session.ixnet_server, session.id)] = session

    def _write_to_db(self, session: Session) -> None:
        """INSERT OR REPLACE the session row. Caller must hold the lock."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO sessions
                (id, ixnet_server, name, username, ports,
                 cp_active, dp_active, utilized, tags, last_polled_at,
                 session_state, error_status, error_count, error_list)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.ixnet_server,
                session.name,
                session.username,
                _ports_to_json(session.ports),
                int(session.cp_active),
                int(session.dp_active),
                int(session.utilized),
                _tags_to_json(session.tags),
                _dt_to_str(session.last_polled),
                session.session_state,
                session.error_status,
                session.error_count,
                json.dumps(session.error_list),
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

        User-set tags are never overwritten by an incoming session that has an
        empty tag list — this guards against poll cycles clobbering tags that
        were added via PATCH /sessions/{server}/{id}/tags.

        Thread-safe: serialised through the instance lock.
        """
        with self._lock:
            existing = self._cache.get((session.ixnet_server, session.id))
            if existing and existing.tags and not session.tags:
                # Carry forward the saved tags so the poller doesn't erase them
                session = session.model_copy(update={"tags": existing.tags})
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

    # ------------------------------------------------------------------
    # Server CRUD
    # ------------------------------------------------------------------

    def _row_to_server(self, row: sqlite3.Row) -> ServerEntry:
        # kcos_info comes from LEFT JOIN kcos_cache k ON s.host = k.host
        kcos_raw = row["kcos_info"] if "kcos_info" in row.keys() else None
        kcos_info = KcosInfo(**json.loads(kcos_raw)) if kcos_raw else None
        return ServerEntry(
            name=row["name"],
            host=row["host"],
            username=row["username"],
            password=row["password"],
            rest_port=row["rest_port"],
            tags=_json_to_tags(row["tags"]),
            kcos_info=kcos_info,
        )

    _SERVER_SELECT = (
        "SELECT s.name, s.host, s.username, s.password, s.rest_port, s.tags,"
        "       k.kcos_info"
        " FROM servers s"
        " LEFT JOIN kcos_cache k ON s.host = k.host"
    )

    def list_servers(self) -> list[ServerEntry]:
        """Return all configured IxNetwork servers."""
        cursor = self._conn.execute(self._SERVER_SELECT + " ORDER BY s.name")
        return [self._row_to_server(row) for row in cursor.fetchall()]

    def get_server(self, name: str) -> ServerEntry | None:
        """Return a single server by name, or None if not found."""
        row = self._conn.execute(
            self._SERVER_SELECT + " WHERE s.name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_server(row)

    def upsert_server(self, server: ServerEntry) -> None:
        """Insert or replace a server entry. Thread-safe."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO servers (name, host, username, password, rest_port, tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    host       = excluded.host,
                    username   = excluded.username,
                    password   = excluded.password,
                    rest_port  = excluded.rest_port,
                    tags       = excluded.tags,
                    updated_at = excluded.updated_at
                """,
                (server.name, server.host, server.username, server.password, server.rest_port,
                 _tags_to_json(server.tags)),
            )
            self._conn.commit()

    def delete_server(self, name: str) -> bool:
        """Delete a server and all its sessions. Returns True if server row deleted."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM servers WHERE name = ?", (name,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                self._conn.execute(
                    "DELETE FROM sessions WHERE ixnet_server = ?", (name,)
                )
                stale = [k for k in self._cache if k[0] == name]
                for k in stale:
                    del self._cache[k]
            self._conn.commit()
            return deleted

    def update_kcos_info(self, host: str, kcos_info: KcosInfo | None) -> None:
        """Persist KCOS SSH probe result keyed by *host* IP/hostname.

        Keying by host (not server name) means the detection survives server
        renames and is shared if the same host is registered under multiple names.
        Passing kcos_info=None removes the cached entry for that host.
        """
        with self._lock:
            if kcos_info is not None:
                self._conn.execute(
                    """
                    INSERT INTO kcos_cache (host, kcos_info, probed_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(host) DO UPDATE SET
                        kcos_info = excluded.kcos_info,
                        probed_at = excluded.probed_at
                    """,
                    (host, kcos_info.model_dump_json()),
                )
            else:
                self._conn.execute("DELETE FROM kcos_cache WHERE host = ?", (host,))
            self._conn.commit()

    def clear_kcos_cache(self) -> int:
        """Delete all rows from kcos_cache. Returns number of rows deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM kcos_cache")
            self._conn.commit()
            return cur.rowcount

    def bulk_upsert_servers(self, servers: list[ServerEntry]) -> list[dict]:
        """Insert-or-replace each server. Returns one result dict per entry.

        Each result: {"name": str, "action": "created"|"updated"|"error", "message": str}
        Thread-safe: single lock around the whole batch.
        """
        results: list[dict] = []
        with self._lock:
            for s in servers:
                try:
                    exists = self._conn.execute(
                        "SELECT 1 FROM servers WHERE name = ?", (s.name,)
                    ).fetchone() is not None
                    self._conn.execute(
                        """
                        INSERT INTO servers (name, host, username, password, rest_port, tags, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(name) DO UPDATE SET
                            host       = excluded.host,
                            username   = excluded.username,
                            password   = excluded.password,
                            rest_port  = excluded.rest_port,
                            tags       = excluded.tags,
                            updated_at = excluded.updated_at
                        """,
                        (s.name, s.host, s.username, s.password, s.rest_port,
                         _tags_to_json(s.tags)),
                    )
                    results.append({
                        "name": s.name,
                        "action": "updated" if exists else "created",
                        "message": "",
                    })
                except Exception as exc:  # noqa: BLE001
                    results.append({"name": s.name, "action": "error", "message": str(exc)})
            self._conn.commit()
        return results

    def bulk_delete_servers(self, names: list[str]) -> list[dict]:
        """Delete servers by name. Returns one result dict per requested name.

        Each result: {"name": str, "action": "deleted"|"not_found"}
        Thread-safe: single lock around the whole batch.
        """
        results: list[dict] = []
        with self._lock:
            for name in names:
                cursor = self._conn.execute(
                    "DELETE FROM servers WHERE name = ?", (name,)
                )
                if cursor.rowcount > 0:
                    self._conn.execute(
                        "DELETE FROM sessions WHERE ixnet_server = ?", (name,)
                    )
                    stale = [k for k in self._cache if k[0] == name]
                    for k in stale:
                        del self._cache[k]
                results.append({
                    "name": name,
                    "action": "deleted" if cursor.rowcount > 0 else "not_found",
                })
            self._conn.commit()
        return results

    def bulk_update_password(self, names: list[str], password: str) -> list[dict]:
        """Update the password field for a set of servers.

        Each result: {"name": str, "action": "updated"|"not_found"}
        """
        results: list[dict] = []
        with self._lock:
            for name in names:
                cursor = self._conn.execute(
                    "UPDATE servers SET password = ?, updated_at = datetime('now') WHERE name = ?",
                    (password, name),
                )
                results.append({
                    "name": name,
                    "action": "updated" if cursor.rowcount > 0 else "not_found",
                })
            self._conn.commit()
        return results

    def seed_servers(self, servers: list[ServerEntry]) -> None:
        """Insert servers that do not already exist (name conflict = skip).

        Used at startup to seed from ixse_config.yaml without overwriting
        any servers already added via the UI.
        """
        with self._lock:
            for s in servers:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO servers (name, host, username, password, rest_port, tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (s.name, s.host, s.username, s.password, s.rest_port, _tags_to_json(s.tags)),
                )
            self._conn.commit()

    def add_server_tag(self, name: str, tag: str) -> ServerEntry:
        """Add *tag* to the server identified by *name*. Idempotent.

        Raises
        ------
        StateError
            If the server does not exist.
        """
        with self._lock:
            server = self.get_server(name)
            if server is None:
                raise StateError(f"Server '{name}' not found")
            if tag in server.tags:
                return server
            new_tags = list(server.tags) + [tag]
            self._conn.execute(
                "UPDATE servers SET tags = ?, updated_at = datetime('now') WHERE name = ?",
                (_tags_to_json(new_tags), name),
            )
            self._conn.commit()
            return server.model_copy(update={"tags": new_tags})

    def remove_server_tag(self, name: str, tag: str) -> ServerEntry:
        """Remove *tag* from the server identified by *name*. Idempotent.

        Raises
        ------
        StateError
            If the server does not exist.
        """
        with self._lock:
            server = self.get_server(name)
            if server is None:
                raise StateError(f"Server '{name}' not found")
            if tag not in server.tags:
                return server
            new_tags = [t for t in server.tags if t != tag]
            self._conn.execute(
                "UPDATE servers SET tags = ?, updated_at = datetime('now') WHERE name = ?",
                (_tags_to_json(new_tags), name),
            )
            self._conn.commit()
            return server.model_copy(update={"tags": new_tags})

    # ------------------------------------------------------------------
    # App settings (key-value store)
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        """Return the stored value for *key*, or *default* if not set."""
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Persist *value* for *key*. Thread-safe."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the SQLite connection. Call on application shutdown."""
        self._conn.close()
