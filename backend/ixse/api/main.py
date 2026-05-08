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
from ixse.api.routers import servers as servers_router
from ixse.api.routers import sessions as sessions_router
from ixse.api.state import FleetState
from ixse.client import RestPyClient, fetch_lldp_map
from ixse.config import AppConfig, ConfigError, IxNetServerConfig, load_config
from ixse.ixn_web import check_ixnetwork_web
from ixse.models import LldpPeerInfo, PollStatus, ServerEntry, Session, SessionPort
from ixse.plane import detect_cp_per_vport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vport → SessionPort mapping
# ---------------------------------------------------------------------------


def _parse_location(raw: str) -> tuple[str, int, int] | None:
    """Parse a vport location string into (chassis, card, port).

    Handles all three formats observed in the wild:
      - Location   field: "10.36.236.121;6;3"   (semicolon-separated — preferred)
      - AssignedTo field: "10.36.236.121:6:3"   (colon-separated)
      - Legacy REST path: "//10.36.236.121/6/3"  (slash-separated)

    Returns None when the string is empty or cannot be parsed.
    """
    raw = raw.strip()
    if not raw:
        return None

    # Try semicolon first (Location field), then colon (AssignedTo), then slash
    for sep in (";", ":", "/"):
        parts = [p for p in raw.split(sep) if p]
        if len(parts) >= 3:
            try:
                return parts[0], int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                continue
    return None


def _parse_vports(
    vports: Any,
    topologies: Any = None,
    lldp_map: dict[tuple[str, int, int], LldpPeerInfo] | None = None,
) -> list[SessionPort]:
    """Map RestPy Vport objects to SessionPort models.

    Uses Vport.Location (semicolons) as the primary location source and falls
    back to Vport.AssignedTo (colons or slashes) when Location is absent.
    Also captures Name, ConnectionState, Type, ActualSpeed, per-port CP status,
    and LLDP neighbor info when an lldp_map is provided.

    Args:
        vports:     RestPy Vport collection from session.Ixnetwork.Vport.find()
        topologies: Optional RestPy Topology collection for per-port CP detection.
                    When None, cp_active defaults to False for all ports.
        lldp_map:   Optional dict from fetch_lldp_map().  Maps
                    (chassis_ip, card, port) → LldpPeerInfo.
                    When None, lldp_peer is left as None on each port.
    """
    ports: list[SessionPort] = []
    for vp in vports:
        vport_name       = str(getattr(vp, "Name",            "") or "")
        connection_state = str(getattr(vp, "ConnectionState", "") or "")
        vport_type       = str(getattr(vp, "Type",            "") or "")
        actual_speed_raw = getattr(vp, "ActualSpeed", 0)
        try:
            actual_speed = int(actual_speed_raw)
        except (TypeError, ValueError):
            actual_speed = 0

        # Prefer Location (semicolon), fall back to AssignedTo (colon/slash)
        location_str = str(getattr(vp, "Location",   "") or "")
        assigned_str = str(getattr(vp, "AssignedTo", "") or "")
        parsed = _parse_location(location_str) or _parse_location(assigned_str)

        if parsed is None:
            continue

        chassis_name, card, port = parsed

        # Per-port CP detection via topology → device group status
        vport_href = str(getattr(vp, "href", "") or "")
        cp_active = (
            detect_cp_per_vport(vport_href, topologies)
            if topologies is not None and vport_href
            else False
        )

        # LLDP neighbor info — look up by (chassis_ip, card, port)
        lldp_peer = (lldp_map or {}).get((chassis_name, card, port))

        try:
            ports.append(
                SessionPort(
                    chassis_name=chassis_name,
                    card=card,
                    port=port,
                    vport_name=vport_name,
                    connection_state=connection_state,
                    vport_type=vport_type,
                    actual_speed=actual_speed,
                    cp_active=cp_active,
                    dp_active=False,  # DP requires IxOS chassis stats (Phase 2)
                    lldp_peer=lldp_peer,
                )
            )
        except (ValueError, IndexError):
            continue
    return ports


# ---------------------------------------------------------------------------
# Sync poll helpers (run in thread executor)
# ---------------------------------------------------------------------------


def poll_server(state: FleetState, server_cfg: IxNetServerConfig | ServerEntry) -> list[Session]:
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

            sess_username = str(getattr(raw_sess, "UserName", "") or "")

            # Fetch topologies once; used for per-port CP detection
            try:
                topologies = raw_sess.Ixnetwork.Topology.find()
            except Exception:  # noqa: BLE001
                topologies = None

            # Fetch LLDP neighbor info for all ports on this session's chassis
            try:
                lldp_map = fetch_lldp_map(raw_sess.Ixnetwork)
            except Exception:  # noqa: BLE001
                lldp_map = {}

            try:
                vports = raw_sess.Ixnetwork.Vport.find()
                ports = _parse_vports(vports, topologies, lldp_map)
            except Exception:  # noqa: BLE001
                ports = []

            # Preserve user-set tags across poll cycles.
            # Tags are written by PATCH /sessions/{server}/{id}/tags and must
            # not be clobbered when the poller refreshes port/plane data.
            existing = state.get_session(server_cfg.name, sess_id)
            preserved_tags = existing.tags if existing is not None else []

            # Session-level cp_active / dp_active / utilized are derived from
            # ports by the Session model_validator — not set explicitly here.
            session = Session(
                id=sess_id,
                name=sess_name,
                username=sess_username,
                ixnet_server=server_cfg.name,
                ports=ports,
                tags=preserved_tags,
                last_polled=now,
            )
            state.upsert_session(session)
            polled.append(session)

        return polled
    finally:
        client.disconnect()


async def _run_poll_cycle(app: FastAPI) -> None:
    """Execute one full poll cycle across all servers stored in the DB."""
    app.state.is_polling = True
    try:
        clear_metrics()
        loop = asyncio.get_event_loop()
        # Read servers from DB — picks up any servers added via the UI at runtime.
        servers = app.state.fleet.list_servers()
        if not servers:
            logger.warning("Poller: no servers configured — skipping poll cycle.")
        for server_cfg in servers:
            try:
                web_snap = await loop.run_in_executor(
                    None, check_ixnetwork_web, server_cfg
                )
                app.state.ixnetwork_web_status[server_cfg.name] = web_snap.model_dump(
                    mode="json"
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "IxNetwork Web probe error for server '%s': %s", server_cfg.name, exc
                )
                now = datetime.now(timezone.utc)
                app.state.ixnetwork_web_status[server_cfg.name] = {
                    "deployment": None,
                    "heartbeat": "red",
                    "auth_path": None,
                    "detail": str(exc),
                    "checked_at": now.isoformat(),
                }

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

    # Seed servers from YAML into DB (INSERT OR IGNORE — never overwrites UI-added entries).
    yaml_servers = [
        ServerEntry(
            name=s.name,
            host=s.host,
            username=s.username,
            password=s.password,
            rest_port=s.rest_port,
        )
        for s in config.ixnet_servers
    ]
    state.seed_servers(yaml_servers)

    app.state.config = config
    app.state.fleet = state
    app.state.last_polled_at: datetime | None = None
    app.state.is_polling: bool = False
    app.state.ixnetwork_web_status = {}

    db_server_count = len(state.list_servers())
    logger.info(
        "IxNetworkSessionExplorer started. %d server(s) in DB (seeded %d from YAML). "
        "Use POST /poll/trigger to fetch sessions.",
        db_server_count,
        len(yaml_servers),
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
    application.include_router(servers_router.router)

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
