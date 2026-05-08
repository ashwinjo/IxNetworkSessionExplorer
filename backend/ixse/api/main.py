"""
FastAPI application: REST server with background polling.

Exposes endpoints for session management, chassis monitoring, and health checks.
Runs a background task that polls all IxNetwork servers every poll_interval_seconds.
Integrates metrics export for Prometheus.

Config is loaded from the path in the IXSE_CONFIG environment variable
(default: "ixse_config.yaml").
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ixse.api.metrics import (
    clear_metrics,
    registry,
    update_server_totals,
    update_session_metrics,
)
from ixse.api.routers import chassis as chassis_router
from ixse.api.routers import health as health_router
from ixse.api.routers import sessions as sessions_router
from ixse.api.state import FleetState
from ixse.client import RestPyClient
from ixse.config import AppConfig, ConfigError, IxNetServerConfig, load_config
from ixse.models import PollStatus, Session, SessionPort
from ixse.plane import detect_cp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vport → SessionPort mapping
# ---------------------------------------------------------------------------


def _parse_vports(vports: Any) -> list[SessionPort]:
    """Map RestPy Vport objects to SessionPort models.

    The AssignedTo field is typically "//chassis-ip/card/port" or empty when
    unassigned.  Unassigned / unparseable ports are silently dropped.
    """
    ports: list[SessionPort] = []
    for vp in vports:
        assigned = str(getattr(vp, "AssignedTo", "") or "").strip("/")
        parts = [p for p in assigned.split("/") if p]
        if len(parts) < 3:
            continue
        try:
            ports.append(
                SessionPort(
                    chassis_name=parts[0],
                    card=int(parts[1]),
                    port=int(parts[2]),
                )
            )
        except (ValueError, IndexError):
            continue
    return ports


# ---------------------------------------------------------------------------
# Sync poll helpers (run in thread executor)
# ---------------------------------------------------------------------------


def poll_server(state: FleetState, server_cfg: IxNetServerConfig) -> list[Session]:
    """Poll a single IxNetwork server and upsert all sessions into *state*.

    Runs synchronously — the async caller wraps this in ``run_in_executor``.

    Returns the list of sessions upserted during this cycle (for metrics).
    """
    client = RestPyClient(server_cfg.host, server_cfg.username, server_cfg.password, server_cfg.rest_port)
    client.connect()
    try:
        now = datetime.now(timezone.utc)
        # get_raw_sessions() uses Sessions.find() — lists existing sessions only,
        # never creates a new one.
        raw_sessions = client.get_raw_sessions()

        polled: list[Session] = []
        for raw_sess in raw_sessions:
            sess_id = str(raw_sess.Id)
            sess_name = str(raw_sess.Name)

            try:
                cp_active = detect_cp(raw_sess.Ixnetwork)
            except Exception:  # noqa: BLE001
                cp_active = False

            try:
                vports = raw_sess.Ixnetwork.Vport.find()
                ports = _parse_vports(vports)
            except Exception:  # noqa: BLE001
                ports = []

            # Data-plane detection requires IxOS chassis config; not wired in
            # MVP — always False until chassis config support is added.
            dp_active = False

            session = Session(
                id=sess_id,
                name=sess_name,
                ixnet_server=server_cfg.name,
                ports=ports,
                cp_active=cp_active,
                dp_active=dp_active,
                last_polled=now,
            )
            state.upsert_session(session)
            polled.append(session)

        return polled
    finally:
        client.disconnect()


async def _run_poll_cycle(app: FastAPI) -> None:
    """Execute one full poll cycle across all configured IxNetwork servers."""
    app.state.is_polling = True
    try:
        clear_metrics()
        loop = asyncio.get_event_loop()
        for server_cfg in app.state.config.ixnet_servers:
            try:
                polled = await loop.run_in_executor(
                    None, poll_server, app.state.fleet, server_cfg
                )
                update_server_totals(server_cfg.name, len(polled))
                for s in polled:
                    update_session_metrics(
                        s.id, server_cfg.name, s.utilized, s.cp_active, s.dp_active
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("Poller error for server '%s': %s", server_cfg.name, exc)
    finally:
        app.state.last_polled_at = datetime.now(timezone.utc)
        app.state.is_polling = False


async def poll_fleet(app: FastAPI) -> None:
    """Background task: poll all servers every ``interval_seconds``."""
    while True:
        await asyncio.sleep(app.state.config.poller.interval_seconds)
        await _run_poll_cycle(app)


# ---------------------------------------------------------------------------
# App factory + lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Load config, initialise state, start poller on startup; tear down on shutdown."""
    config_path = os.environ.get("IXSE_CONFIG", "ixse_config.yaml")
    try:
        config: AppConfig = load_config(config_path)
    except ConfigError as exc:
        logger.error("Failed to load config from '%s': %s", config_path, exc)
        raise

    db_path = os.environ.get("IXSE_DB", "ixse.db")
    state = FleetState(db_path=db_path)

    app.state.config = config
    app.state.fleet = state
    app.state.last_polled_at: datetime | None = None
    app.state.is_polling: bool = False

    logger.info(
        "IxNetworkSessionExplorer started. Background poller disabled — use POST /poll/trigger to fetch manually. %d server(s) configured.",
        len(config.ixnet_servers),
    )

    yield

    state.close()
    logger.info("IxNetworkSessionExplorer shut down cleanly.")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    application = FastAPI(
        title="IxNetwork Session Explorer",
        description="Unified session manager for IxNetwork lab environments.",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Note: tighten for production
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(sessions_router.router)
    application.include_router(chassis_router.router)
    application.include_router(health_router.router)

    # ------------------------------------------------------------------
    # Poll control endpoints (inline — not a separate router)
    # ------------------------------------------------------------------

    @application.post(
        "/poll/trigger",
        summary="Force an immediate poll cycle",
        tags=["poll"],
    )
    async def trigger_poll(request: Request) -> dict:  # type: ignore[return]
        """Kick off a poll cycle immediately without waiting for the next interval."""
        if request.app.state.is_polling:
            return {
                "status": "already_polling",
                "message": "A poll cycle is already in progress.",
            }
        asyncio.create_task(_run_poll_cycle(request.app))
        return {"status": "triggered", "message": "Poll cycle started."}

    @application.get(
        "/poll/status",
        response_model=PollStatus,
        summary="Current poller state",
        tags=["poll"],
    )
    async def poll_status(request: Request) -> PollStatus:
        last = request.app.state.last_polled_at
        interval = request.app.state.config.poller.interval_seconds
        next_scheduled = (last + timedelta(seconds=interval)) if last else None
        return PollStatus(
            last_polled_at=last,
            next_scheduled=next_scheduled,
            is_polling=request.app.state.is_polling,
        )

    # ------------------------------------------------------------------
    # Prometheus metrics endpoint
    # ------------------------------------------------------------------

    @application.get(
        "/metrics",
        summary="Prometheus metrics",
        tags=["observability"],
        include_in_schema=False,
    )
    async def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    # ------------------------------------------------------------------
    # Frontend static files — mounted LAST so all API routes take priority.
    # StaticFiles with html=True serves index.html for "/" and any path
    # that doesn't match an existing file.
    # Resolved: backend/ixse/api/main.py → ../../../../frontend
    # ------------------------------------------------------------------

    _frontend_dir = Path(__file__).parent.parent.parent.parent / "frontend"

    if _frontend_dir.exists():
        application.mount(
            "/",
            StaticFiles(directory=str(_frontend_dir), html=True),
            name="frontend",
        )
    else:
        @application.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return application


# Module-level app instance used by uvicorn and tests.
app = create_app()
