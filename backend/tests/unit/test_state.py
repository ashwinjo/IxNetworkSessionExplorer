"""
Unit tests for ixse/api/state.py.

TDD — written before the full implementation.
Coverage:
  1.  upsert creates new session, get_session returns it
  2.  upsert updates existing session (same id+server)
  3.  get_sessions filters by server
  4.  get_sessions filters by utilized=True
  5.  add_tag adds tag, persists to DB
  6.  remove_tag removes tag
  7.  add_tag on missing session raises StateError
  8.  delete_session removes from DB and cache
  9.  Thread safety: 10 threads upsert concurrently, all sessions present
  10. DB persistence: close + reopen, sessions still there
"""

import threading
import tempfile
import os
from datetime import datetime, timezone

import pytest

from ixse.models import Session, SessionPort
from ixse.api.state import FleetState, StateError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def make_port(chassis: str = "lab-01", card: int = 1, port: int = 1) -> SessionPort:
    return SessionPort(chassis_name=chassis, card=card, port=port)


def make_session(
    session_id: str = "sess-001",
    server: str = "ixnet-server-01",
    name: str = "bgp-test",
    cp_active: bool = True,
    dp_active: bool = False,
    tags: list[str] | None = None,
    ports: list[SessionPort] | None = None,
) -> Session:
    return Session(
        id=session_id,
        name=name,
        ixnet_server=server,
        ports=ports if ports is not None else [make_port()],
        cp_active=cp_active,
        dp_active=dp_active,
        tags=tags if tags is not None else [],
        last_polled=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state() -> FleetState:
    """In-memory FleetState for isolated, fast unit tests."""
    fs = FleetState(db_path=":memory:")
    yield fs
    fs.close()


@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    return str(tmp_path / "test_fleet.db")


# ---------------------------------------------------------------------------
# 1. upsert creates new session; get_session returns it
# ---------------------------------------------------------------------------


class TestUpsertAndGet:
    def test_upsert_and_retrieve(self, state: FleetState):
        sess = make_session()
        state.upsert_session(sess)
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert result.id == "sess-001"
        assert result.ixnet_server == "ixnet-server-01"
        assert result.name == "bgp-test"

    def test_get_nonexistent_returns_none(self, state: FleetState):
        result = state.get_session("ixnet-server-01", "no-such-session")
        assert result is None

    def test_upsert_preserves_ports(self, state: FleetState):
        ports = [make_port(card=1, port=i) for i in range(1, 4)]
        sess = make_session(ports=ports)
        state.upsert_session(sess)
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert len(result.ports) == 3

    def test_upsert_preserves_tags(self, state: FleetState):
        sess = make_session(tags=["bgp", "lab-a"])
        state.upsert_session(sess)
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert set(result.tags) == {"bgp", "lab-a"}

    def test_upsert_preserves_plane_status(self, state: FleetState):
        sess = make_session(cp_active=True, dp_active=True)
        state.upsert_session(sess)
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert result.cp_active is True
        assert result.dp_active is True
        assert result.utilized is True  # auto-computed by Session validator


# ---------------------------------------------------------------------------
# 2. upsert updates existing session (same id + server)
# ---------------------------------------------------------------------------


class TestUpsertUpdate:
    def test_upsert_overwrites_existing(self, state: FleetState):
        sess = make_session(name="bgp-test", cp_active=False, dp_active=False)
        state.upsert_session(sess)

        updated = make_session(name="bgp-test-v2", cp_active=True, dp_active=True)
        state.upsert_session(updated)

        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert result.name == "bgp-test-v2"
        assert result.cp_active is True
        assert result.dp_active is True

    def test_upsert_update_preserves_same_primary_key(self, state: FleetState):
        for name in ("first", "second", "third"):
            state.upsert_session(make_session(name=name))

        # Only one session should exist — same (id, server) key
        all_sessions = state.get_all()
        assert len(all_sessions) == 1
        assert all_sessions[0].name == "third"


# ---------------------------------------------------------------------------
# 3. get_sessions filters by server
# ---------------------------------------------------------------------------


class TestGetSessionsServerFilter:
    def _populate(self, state: FleetState):
        state.upsert_session(make_session(session_id="s1", server="server-a", name="s1"))
        state.upsert_session(make_session(session_id="s2", server="server-a", name="s2"))
        state.upsert_session(make_session(session_id="s3", server="server-b", name="s3"))

    def test_filter_by_server_a(self, state: FleetState):
        self._populate(state)
        results = state.get_sessions(server="server-a")
        assert len(results) == 2
        assert all(s.ixnet_server == "server-a" for s in results)

    def test_filter_by_server_b(self, state: FleetState):
        self._populate(state)
        results = state.get_sessions(server="server-b")
        assert len(results) == 1
        assert results[0].id == "s3"

    def test_no_filter_returns_all(self, state: FleetState):
        self._populate(state)
        results = state.get_sessions()
        assert len(results) == 3

    def test_unknown_server_returns_empty(self, state: FleetState):
        self._populate(state)
        results = state.get_sessions(server="server-z")
        assert results == []


# ---------------------------------------------------------------------------
# 4. get_sessions filters by utilized=True
# ---------------------------------------------------------------------------


class TestGetSessionsUtilizedFilter:
    def _populate(self, state: FleetState):
        # utilized = cp_active AND dp_active
        state.upsert_session(
            make_session(session_id="u1", cp_active=True, dp_active=True)   # utilized
        )
        state.upsert_session(
            make_session(session_id="u2", cp_active=True, dp_active=False)  # not utilized
        )
        state.upsert_session(
            make_session(session_id="u3", cp_active=False, dp_active=False) # not utilized
        )

    def test_utilized_true_filter(self, state: FleetState):
        self._populate(state)
        results = state.get_sessions(utilized=True)
        assert len(results) == 1
        assert results[0].id == "u1"

    def test_utilized_false_filter(self, state: FleetState):
        self._populate(state)
        results = state.get_sessions(utilized=False)
        assert len(results) == 2
        ids = {s.id for s in results}
        assert ids == {"u2", "u3"}

    def test_combined_server_and_utilized_filter(self, state: FleetState):
        state.upsert_session(
            make_session(session_id="x1", server="srv-x", cp_active=True, dp_active=True)
        )
        state.upsert_session(
            make_session(session_id="x2", server="srv-x", cp_active=False, dp_active=False)
        )
        state.upsert_session(
            make_session(session_id="y1", server="srv-y", cp_active=True, dp_active=True)
        )
        results = state.get_sessions(server="srv-x", utilized=True)
        assert len(results) == 1
        assert results[0].id == "x1"


# ---------------------------------------------------------------------------
# 5. add_tag adds tag, persists to DB
# ---------------------------------------------------------------------------


class TestAddTag:
    def test_add_tag_returns_updated_session(self, state: FleetState):
        state.upsert_session(make_session())
        updated = state.add_tag("ixnet-server-01", "sess-001", "new-tag")
        assert "new-tag" in updated.tags

    def test_add_tag_visible_via_get_session(self, state: FleetState):
        state.upsert_session(make_session())
        state.add_tag("ixnet-server-01", "sess-001", "new-tag")
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert "new-tag" in result.tags

    def test_add_multiple_tags(self, state: FleetState):
        state.upsert_session(make_session())
        state.add_tag("ixnet-server-01", "sess-001", "tag-a")
        state.add_tag("ixnet-server-01", "sess-001", "tag-b")
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert {"tag-a", "tag-b"}.issubset(set(result.tags))

    def test_add_duplicate_tag_is_idempotent(self, state: FleetState):
        state.upsert_session(make_session(tags=["existing"]))
        state.add_tag("ixnet-server-01", "sess-001", "existing")
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert result.tags.count("existing") == 1

    def test_add_tag_persists_to_db(self, tmp_db_path: str):
        """Tag added then DB closed+reopened must still be present."""
        fs = FleetState(db_path=tmp_db_path)
        fs.upsert_session(make_session())
        fs.add_tag("ixnet-server-01", "sess-001", "persisted-tag")
        fs.close()

        fs2 = FleetState(db_path=tmp_db_path)
        result = fs2.get_session("ixnet-server-01", "sess-001")
        fs2.close()

        assert result is not None
        assert "persisted-tag" in result.tags


# ---------------------------------------------------------------------------
# 6. remove_tag removes tag
# ---------------------------------------------------------------------------


class TestRemoveTag:
    def test_remove_existing_tag(self, state: FleetState):
        state.upsert_session(make_session(tags=["keep", "remove-me"]))
        updated = state.remove_tag("ixnet-server-01", "sess-001", "remove-me")
        assert "remove-me" not in updated.tags
        assert "keep" in updated.tags

    def test_remove_tag_visible_via_get_session(self, state: FleetState):
        state.upsert_session(make_session(tags=["alpha", "beta"]))
        state.remove_tag("ixnet-server-01", "sess-001", "alpha")
        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert "alpha" not in result.tags
        assert "beta" in result.tags

    def test_remove_nonexistent_tag_is_noop(self, state: FleetState):
        """Removing a tag that doesn't exist should not raise — idempotent."""
        state.upsert_session(make_session(tags=["only-tag"]))
        updated = state.remove_tag("ixnet-server-01", "sess-001", "ghost-tag")
        assert updated.tags == ["only-tag"]

    def test_remove_all_tags(self, state: FleetState):
        state.upsert_session(make_session(tags=["solo"]))
        updated = state.remove_tag("ixnet-server-01", "sess-001", "solo")
        assert updated.tags == []


# ---------------------------------------------------------------------------
# 7. add_tag on missing session raises StateError
# ---------------------------------------------------------------------------


class TestStateError:
    def test_add_tag_missing_session_raises(self, state: FleetState):
        with pytest.raises(StateError, match="not found"):
            state.add_tag("ixnet-server-01", "no-such-id", "tag")

    def test_remove_tag_missing_session_raises(self, state: FleetState):
        with pytest.raises(StateError, match="not found"):
            state.remove_tag("ixnet-server-01", "no-such-id", "tag")

    def test_delete_session_missing_raises(self, state: FleetState):
        with pytest.raises(StateError, match="not found"):
            state.delete_session("ixnet-server-01", "no-such-id")


# ---------------------------------------------------------------------------
# 8. delete_session removes from DB and cache
# ---------------------------------------------------------------------------


class TestDeleteSession:
    def test_delete_removes_from_cache(self, state: FleetState):
        state.upsert_session(make_session())
        state.delete_session("ixnet-server-01", "sess-001")
        assert state.get_session("ixnet-server-01", "sess-001") is None

    def test_delete_removes_from_db(self, tmp_db_path: str):
        fs = FleetState(db_path=tmp_db_path)
        fs.upsert_session(make_session())
        fs.delete_session("ixnet-server-01", "sess-001")
        fs.close()

        fs2 = FleetState(db_path=tmp_db_path)
        result = fs2.get_session("ixnet-server-01", "sess-001")
        fs2.close()

        assert result is None

    def test_delete_does_not_affect_other_sessions(self, state: FleetState):
        state.upsert_session(make_session(session_id="del-me", server="srv"))
        state.upsert_session(make_session(session_id="keep-me", server="srv"))
        state.delete_session("srv", "del-me")

        assert state.get_session("srv", "del-me") is None
        assert state.get_session("srv", "keep-me") is not None

    def test_get_all_after_delete_excludes_deleted(self, state: FleetState):
        state.upsert_session(make_session(session_id="a", server="srv"))
        state.upsert_session(make_session(session_id="b", server="srv"))
        state.delete_session("srv", "a")
        remaining = state.get_all()
        ids = {s.id for s in remaining}
        assert "a" not in ids
        assert "b" in ids


# ---------------------------------------------------------------------------
# 9. Thread safety: 10 threads upsert concurrently
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_upserts(self, state: FleetState):
        """10 threads each upsert a unique session — all must be present after."""
        n_threads = 10
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                sess = make_session(
                    session_id=f"thread-sess-{idx}",
                    server="concurrent-server",
                    name=f"session-{idx}",
                )
                state.upsert_session(sess)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Exceptions in worker threads: {errors}"

        results = state.get_sessions(server="concurrent-server")
        assert len(results) == n_threads
        ids = {s.id for s in results}
        expected = {f"thread-sess-{i}" for i in range(n_threads)}
        assert ids == expected

    def test_concurrent_tag_operations(self, state: FleetState):
        """Multiple threads adding distinct tags to the same session — no data loss."""
        state.upsert_session(make_session())
        n_threads = 8
        errors: list[Exception] = []

        def add_tag_worker(idx: int) -> None:
            try:
                state.add_tag("ixnet-server-01", "sess-001", f"tag-{idx}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=add_tag_worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Exceptions in tag worker threads: {errors}"

        result = state.get_session("ixnet-server-01", "sess-001")
        assert result is not None
        assert len(result.tags) == n_threads


# ---------------------------------------------------------------------------
# 10. DB persistence: close + reopen, sessions still there
# ---------------------------------------------------------------------------


class TestDbPersistence:
    def test_sessions_survive_close_reopen(self, tmp_db_path: str):
        fs = FleetState(db_path=tmp_db_path)
        sess_a = make_session(session_id="persist-a", name="persist-session-a")
        sess_b = make_session(session_id="persist-b", name="persist-session-b")
        fs.upsert_session(sess_a)
        fs.upsert_session(sess_b)
        fs.close()

        fs2 = FleetState(db_path=tmp_db_path)
        result_a = fs2.get_session("ixnet-server-01", "persist-a")
        result_b = fs2.get_session("ixnet-server-01", "persist-b")
        all_sessions = fs2.get_all()
        fs2.close()

        assert result_a is not None
        assert result_a.name == "persist-session-a"
        assert result_b is not None
        assert result_b.name == "persist-session-b"
        assert len(all_sessions) == 2

    def test_plane_status_persists(self, tmp_db_path: str):
        fs = FleetState(db_path=tmp_db_path)
        fs.upsert_session(make_session(cp_active=True, dp_active=True))
        fs.close()

        fs2 = FleetState(db_path=tmp_db_path)
        result = fs2.get_session("ixnet-server-01", "sess-001")
        fs2.close()

        assert result is not None
        assert result.cp_active is True
        assert result.dp_active is True
        assert result.utilized is True

    def test_ports_persist(self, tmp_db_path: str):
        ports = [make_port(card=c, port=p) for c, p in [(1, 1), (1, 2), (2, 1)]]
        fs = FleetState(db_path=tmp_db_path)
        fs.upsert_session(make_session(ports=ports))
        fs.close()

        fs2 = FleetState(db_path=tmp_db_path)
        result = fs2.get_session("ixnet-server-01", "sess-001")
        fs2.close()

        assert result is not None
        assert len(result.ports) == 3

    def test_cache_populated_on_reopen(self, tmp_db_path: str):
        """After reopen, in-memory cache must be warm (get_session must not return None)."""
        fs = FleetState(db_path=tmp_db_path)
        fs.upsert_session(make_session(session_id="warm-me"))
        fs.close()

        fs2 = FleetState(db_path=tmp_db_path)
        # Access via cache — no additional DB query
        result = fs2.get_session("ixnet-server-01", "warm-me")
        fs2.close()

        assert result is not None
        assert result.id == "warm-me"
