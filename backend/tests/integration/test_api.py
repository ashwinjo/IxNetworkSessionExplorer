"""
Integration tests for the IxNetworkSessionExplorer REST API.

These tests exercise the full FastAPI app (including router wiring and
response envelopes) but replace all external I/O with mocks:
  - FleetState uses an in-memory SQLite DB
  - RestPyClient is mocked (no real IxNetwork connection)

The lifespan context is bypassed by injecting state directly into
``app.state`` before issuing requests.

Test scenarios:
  A. Lifecycle smoke tests
     1.  GET /health — basic response shape (router stub returns None — 200 OK)
     2.  GET /chassis — basic response shape
     3.  GET /docs — OpenAPI docs are reachable
  B. Sessions CRUD flow
     4.  Empty fleet: GET /sessions → empty list
     5.  Upsert two sessions: GET /sessions → both returned
     6.  GET /sessions?server=X → filtered
     7.  GET /sessions?tag=bgp → filtered
     8.  GET /sessions/{s}/{id} → full detail
     9.  GET /sessions/{s}/{id} 404 → error shape
     10. PATCH /sessions/{s}/{id}/tags?add → tag applied
     11. PATCH /sessions/{s}/{id}/tags?remove → tag removed
     12. PATCH /sessions/{s}/{id}/tags → 404 body on unknown session
     13. DELETE without confirm → 400
     14. DELETE with confirm, mocked kill → 200, session gone
     15. DELETE unknown → 404
  C. Poll control
     16. GET /poll/status → correct initial shape
     17. POST /poll/trigger (not polling) → triggered
     18. POST /poll/trigger (already polling) → already_polling
  D. Observability
     19. GET /metrics → Prometheus text format
     20. GET /metrics after metrics update → contains ixse_ metric names
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ixse.api.main import create_app
from ixse.api.metrics import update_server_totals, update_session_metrics
from ixse.api.state import FleetState
from ixse.config import AppConfig, IxNetServerConfig, PollerConfig
from ixse.models import Session, SessionPort

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "s1",
    server: str = "ixnet-sv-01",
    name: str = "test-session",
    cp_active: bool = True,
    dp_active: bool = False,
    tags: list[str] | None = None,
) -> Session:
    return Session(
        id=session_id,
        name=name,
        ixnet_server=server,
        ports=[SessionPort(chassis_name="lab-01", card=1, port=1)],
        cp_active=cp_active,
        dp_active=dp_active,
        tags=tags or [],
        last_polled=datetime.now(UTC),
    )


def _make_config(server_name: str = "ixnet-sv-01") -> AppConfig:
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fleet() -> FleetState:
    return FleetState(db_path=":memory:")


@pytest.fixture()
def api_client(fleet: FleetState) -> TestClient:
    """TestClient with injected in-memory state; lifespan bypassed."""
    application = create_app()
    application.router.lifespan_context = None  # type: ignore[assignment]

    tc = TestClient(application, raise_server_exceptions=True)

    application.state.fleet = fleet
    application.state.config = _make_config()
    application.state.last_polled_at = None
    application.state.is_polling = False

    return tc


# ---------------------------------------------------------------------------
# A. Lifecycle smoke tests
# ---------------------------------------------------------------------------


class TestLifecycleSmoke:
    def test_health_endpoint_reachable(self, api_client: TestClient) -> None:
        resp = api_client.get("/health/")
        # health router stubs return None → FastAPI serialises to null → 200 OK
        assert resp.status_code == 200

    def test_chassis_endpoint_reachable(self, api_client: TestClient) -> None:
        resp = api_client.get("/chassis/")
        assert resp.status_code == 200

    def test_openapi_docs_reachable(self, api_client: TestClient) -> None:
        resp = api_client.get("/docs")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# B. Sessions CRUD flow
# ---------------------------------------------------------------------------


class TestSessionsCRUD:
    # --- list ---

    def _all_ids(self, body: dict) -> set[str]:
        return {s["id"] for srv in body["data"]["servers"] for s in srv["sessions"]}

    def test_empty_fleet_returns_server_with_no_sessions(self, api_client: TestClient) -> None:
        resp = api_client.get("/sessions/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        # Config has ixnet-sv-01 — appears with 0 sessions
        servers = body["data"]["servers"]
        assert any(s["name"] == "ixnet-sv-01" for s in servers)
        sv = next(s for s in servers if s["name"] == "ixnet-sv-01")
        assert sv["sessions"] == []

    def test_upserted_sessions_appear_in_list(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ixnet-sv-01"))
        fleet.upsert_session(_make_session("s2", "ixnet-sv-01"))

        resp = api_client.get("/sessions/")
        assert self._all_ids(resp.json()) == {"s1", "s2"}

    def test_filter_by_server(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ixnet-sv-01"))

        resp = api_client.get("/sessions/?server=ixnet-sv-01")
        body = resp.json()
        servers = body["data"]["servers"]
        assert len(servers) == 1
        assert servers[0]["sessions"][0]["id"] == "s1"

    def test_filter_by_tag(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ixnet-sv-01", tags=["bgp"]))
        fleet.upsert_session(_make_session("s2", "ixnet-sv-01", tags=["ospf"]))

        resp = api_client.get("/sessions/?tag=bgp")
        assert self._all_ids(resp.json()) == {"s1"}

    # --- detail ---

    def test_get_session_detail(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        sess = _make_session("s1", "ixnet-sv-01", cp_active=True, dp_active=True)
        fleet.upsert_session(sess)

        resp = api_client.get("/sessions/ixnet-sv-01/s1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == "s1"
        assert data["cp_active"] is True
        assert data["utilized"] is True  # cp AND dp

    def test_get_session_detail_404(self, api_client: TestClient) -> None:
        resp = api_client.get("/sessions/ixnet-sv-01/unknown")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    # --- tags ---

    def test_patch_tags_add(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ixnet-sv-01"))
        resp = api_client.patch(
            "/sessions/ixnet-sv-01/s1/tags",
            json={"add": ["bgp", "lab-a"], "remove": []},
        )
        assert resp.status_code == 200
        tags = resp.json()["data"]["tags"]
        assert "bgp" in tags
        assert "lab-a" in tags

    def test_patch_tags_remove(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(
            _make_session("s1", "ixnet-sv-01", tags=["bgp", "lab-a"])
        )
        resp = api_client.patch(
            "/sessions/ixnet-sv-01/s1/tags",
            json={"add": [], "remove": ["bgp"]},
        )
        assert resp.status_code == 200
        tags = resp.json()["data"]["tags"]
        assert "bgp" not in tags
        assert "lab-a" in tags

    def test_patch_tags_404(self, api_client: TestClient) -> None:
        resp = api_client.patch(
            "/sessions/ixnet-sv-01/no-such/tags",
            json={"add": ["x"], "remove": []},
        )
        assert resp.status_code == 404

    # --- delete ---

    def test_delete_without_confirm_is_400(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ixnet-sv-01"))
        resp = api_client.delete("/sessions/ixnet-sv-01/s1")
        assert resp.status_code == 400

    def test_delete_with_confirm_removes_session(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ixnet-sv-01"))

        mock_rp = MagicMock()
        with patch(
            "ixse.api.routers.sessions.RestPyClient", return_value=mock_rp
        ):
            resp = api_client.delete("/sessions/ixnet-sv-01/s1?confirm=true")

        assert resp.status_code == 200
        assert "deleted" in resp.json()["data"]["message"].lower()
        assert fleet.get_session("ixnet-sv-01", "s1") is None
        mock_rp.connect.assert_called_once()
        mock_rp.kill_session.assert_called_once_with("s1")

    def test_delete_unknown_session_is_404(self, api_client: TestClient) -> None:
        resp = api_client.delete("/sessions/ixnet-sv-01/ghost?confirm=true")
        assert resp.status_code == 404

    def test_delete_unknown_server_in_config_is_404(
        self, api_client: TestClient, fleet: FleetState
    ) -> None:
        fleet.upsert_session(_make_session("s1", "ghost-server"))
        resp = api_client.delete("/sessions/ghost-server/s1?confirm=true")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# C. Poll control
# ---------------------------------------------------------------------------


class TestPollControl:
    def test_poll_status_initial(self, api_client: TestClient) -> None:
        resp = api_client.get("/poll/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_polled_at"] is None
        assert body["next_scheduled"] is None
        assert body["is_polling"] is False

    def test_poll_trigger_when_idle(self, api_client: TestClient) -> None:
        with patch("ixse.api.main._run_poll_cycle"):
            resp = api_client.post("/poll/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "triggered"

    def test_poll_trigger_when_busy(self, api_client: TestClient) -> None:
        api_client.app.state.is_polling = True
        resp = api_client.post("/poll/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_polling"


# ---------------------------------------------------------------------------
# D. Observability
# ---------------------------------------------------------------------------


class TestObservability:
    def test_metrics_endpoint_returns_text(self, api_client: TestClient) -> None:
        resp = api_client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contain_ixse_names_after_update(
        self, api_client: TestClient
    ) -> None:
        update_server_totals("ixnet-sv-01", 2)
        update_session_metrics("s1", "ixnet-sv-01", True, True, True)

        resp = api_client.get("/metrics")
        text = resp.text
        assert "ixse_sessions_total" in text
        assert "ixse_session_utilized" in text
