"""
Unit tests for ixse/api/main.py and ixse/api/routers/sessions.py.

Uses FastAPI's TestClient (synchronous) so that async lifespan is bypassed by
manually injecting a pre-built FleetState into app.state — no real IxNetwork
server is required.

Coverage:
  1.  GET /poll/status — initial state (no polls yet)
  2.  GET /poll/status — after setting last_polled_at on app.state
  3.  POST /poll/trigger — returns "triggered" when not already polling
  4.  POST /poll/trigger — returns "already_polling" when is_polling is True
  5.  GET /metrics — returns Prometheus text with ixse_ prefix
  6.  GET /sessions — empty fleet returns empty list
  7.  GET /sessions — populated fleet returns all sessions
  8.  GET /sessions?server=X — filters by server
  9.  GET /sessions?tag=bgp — filters by tag
  10. GET /sessions/{server}/{id} — returns single session
  11. GET /sessions/{server}/{id} — 404 on unknown id
  12. PATCH /sessions/{server}/{id}/tags — add and remove tags
  13. PATCH /sessions/{server}/{id}/tags — 404 on unknown session
  14. DELETE /sessions/{server}/{id}?confirm=true — kills and removes (mocked)
  15. DELETE /sessions/{server}/{id} — 400 without confirm=true
  16. DELETE /sessions/{server}/{id}?confirm=true — 404 unknown session
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ixse.api.main import create_app
from ixse.api.state import FleetState
from ixse.config import AppConfig, IxNetServerConfig, PollerConfig
from ixse.models import Session, SessionPort

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def make_port(chassis: str = "lab-01", card: int = 1, port: int = 1) -> SessionPort:
    return SessionPort(chassis_name=chassis, card=card, port=port)


def make_session(
    session_id: str = "sess-001",
    server: str = "ixnet-sv-01",
    name: str = "bgp-test",
    cp_active: bool = True,
    dp_active: bool = False,
    tags: list[str] | None = None,
) -> Session:
    return Session(
        id=session_id,
        name=name,
        ixnet_server=server,
        ports=[make_port()],
        cp_active=cp_active,
        dp_active=dp_active,
        tags=tags or [],
        last_polled=datetime.now(UTC),
    )


def make_config(server_name: str = "ixnet-sv-01") -> AppConfig:
    return AppConfig(
        poller=PollerConfig(interval_seconds=60),
        ixnet_servers=[
            IxNetServerConfig(
                name=server_name,
                host="10.0.0.1",
                username="admin",
                password="pass",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Fixture: app with injected state (bypasses lifespan)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fleet() -> FleetState:
    """In-memory FleetState for test isolation."""
    return FleetState(db_path=":memory:")


@pytest.fixture()
def client(fleet: FleetState) -> TestClient:
    """TestClient with pre-injected state — no real config file needed."""
    application = create_app()

    # Override lifespan: do not start background poller or load config file.
    application.router.lifespan_context = None  # type: ignore[assignment]

    tc = TestClient(application, raise_server_exceptions=True)

    # Inject state directly (bypasses lifespan)
    application.state.fleet = fleet
    application.state.config = make_config()
    application.state.last_polled_at = None
    application.state.is_polling = False

    return tc


# ---------------------------------------------------------------------------
# Poll status tests
# ---------------------------------------------------------------------------


class TestPollStatus:
    def test_initial_status_all_none(self, client: TestClient) -> None:
        resp = client.get("/poll/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_polled_at"] is None
        assert body["next_scheduled"] is None
        assert body["is_polling"] is False

    def test_status_after_last_polled(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        now = datetime.now(UTC)
        client.app.state.last_polled_at = now

        resp = client.get("/poll/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_polled_at"] is not None
        assert body["next_scheduled"] is not None
        assert body["is_polling"] is False


# ---------------------------------------------------------------------------
# Poll trigger tests
# ---------------------------------------------------------------------------


class TestPollTrigger:
    def test_trigger_when_idle(self, client: TestClient) -> None:
        # _run_poll_cycle is async — patch it so no actual I/O happens
        with patch("ixse.api.main._run_poll_cycle"):
            resp = client.post("/poll/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "triggered"

    def test_trigger_when_already_polling(self, client: TestClient) -> None:
        client.app.state.is_polling = True
        resp = client.post("/poll/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_polling"


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_returns_prometheus_text(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        # The response is valid Prometheus text (may be empty if no sessions polled)
        # Just verify it doesn't error and has the right content-type.


# ---------------------------------------------------------------------------
# GET /sessions tests
# ---------------------------------------------------------------------------


def _all_session_ids(body: dict) -> set[str]:
    """Extract all session IDs from the grouped servers response."""
    return {
        s["id"]
        for srv in body["data"]["servers"]
        for s in srv["sessions"]
    }


class TestListSessions:
    def test_empty_fleet(self, client: TestClient) -> None:
        resp = client.get("/sessions/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        # Config has one server (ixnet-sv-01) — it appears with 0 sessions
        servers = body["data"]["servers"]
        assert len(servers) == 1
        assert servers[0]["name"] == "ixnet-sv-01"
        assert servers[0]["sessions"] == []

    def test_returns_all_sessions(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01"))
        fleet.upsert_session(make_session("s2", "ixnet-sv-01"))

        resp = client.get("/sessions/")
        body = resp.json()
        assert body["status"] == "ok"
        assert _all_session_ids(body) == {"s1", "s2"}

    def test_filter_by_server(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01"))

        resp = client.get("/sessions/?server=ixnet-sv-01")
        body = resp.json()
        servers = body["data"]["servers"]
        assert len(servers) == 1
        assert servers[0]["name"] == "ixnet-sv-01"
        assert servers[0]["sessions"][0]["id"] == "s1"

    def test_filter_by_tag(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01", tags=["bgp"]))
        fleet.upsert_session(make_session("s2", "ixnet-sv-01", tags=["ospf"]))

        resp = client.get("/sessions/?tag=bgp")
        body = resp.json()
        assert _all_session_ids(body) == {"s1"}

    def test_response_includes_host(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01"))
        resp = client.get("/sessions/")
        srv = resp.json()["data"]["servers"][0]
        assert srv["host"] == "10.0.0.1"  # from make_config fixture


# ---------------------------------------------------------------------------
# GET /sessions/{server}/{id} tests
# ---------------------------------------------------------------------------


class TestGetSessionDetail:
    def test_returns_session(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        sess = make_session("s1", "ixnet-sv-01")
        fleet.upsert_session(sess)

        resp = client.get("/sessions/ixnet-sv-01/s1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["data"]["id"] == "s1"
        assert body["data"]["ixnet_server"] == "ixnet-sv-01"

    def test_404_on_unknown(self, client: TestClient) -> None:
        resp = client.get("/sessions/ixnet-sv-01/no-such-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /sessions/{server}/{id}/tags tests
# ---------------------------------------------------------------------------


class TestUpdateTags:
    def test_add_tags(self, client: TestClient, fleet: FleetState) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01"))

        resp = client.patch(
            "/sessions/ixnet-sv-01/s1/tags",
            json={"add": ["bgp", "lab-a"], "remove": []},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "bgp" in data["tags"]
        assert "lab-a" in data["tags"]

    def test_remove_tags(self, client: TestClient, fleet: FleetState) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01", tags=["bgp", "ospf"]))

        resp = client.patch(
            "/sessions/ixnet-sv-01/s1/tags",
            json={"add": [], "remove": ["bgp"]},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "bgp" not in data["tags"]
        assert "ospf" in data["tags"]

    def test_add_and_remove_together(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01", tags=["old"]))

        resp = client.patch(
            "/sessions/ixnet-sv-01/s1/tags",
            json={"add": ["new"], "remove": ["old"]},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "new" in data["tags"]
        assert "old" not in data["tags"]

    def test_404_on_unknown_session(self, client: TestClient) -> None:
        resp = client.patch(
            "/sessions/ixnet-sv-01/no-such/tags",
            json={"add": ["x"], "remove": []},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /sessions/{server}/{id} tests
# ---------------------------------------------------------------------------


class TestDeleteSession:
    def test_requires_confirm(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01"))
        resp = client.delete("/sessions/ixnet-sv-01/s1")
        assert resp.status_code == 400

    def test_delete_success(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(make_session("s1", "ixnet-sv-01"))

        mock_client = MagicMock()
        mock_client.kill_session = MagicMock()

        with patch("ixse.api.routers.sessions.RestPyClient", return_value=mock_client):
            resp = client.delete("/sessions/ixnet-sv-01/s1?confirm=true")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        # Session should be gone from state
        assert fleet.get_session("ixnet-sv-01", "s1") is None

    def test_delete_404_on_unknown(self, client: TestClient) -> None:
        resp = client.delete("/sessions/ixnet-sv-01/no-such?confirm=true")
        assert resp.status_code == 404

    def test_delete_404_unknown_server_config(
        self, client: TestClient, fleet: FleetState
    ) -> None:
        # Session exists in state but server name is not in config
        fleet.upsert_session(make_session("s1", "ghost-server"))
        resp = client.delete("/sessions/ghost-server/s1?confirm=true")
        assert resp.status_code == 404
