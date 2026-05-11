"""
Sessions endpoints: GET /sessions, PATCH tags, DELETE session.

Provides REST API for listing, filtering, tagging, and destroying
IxNetwork sessions.

All endpoints read app state via ``request.app.state`` so that the
same FastAPI instance can be used in tests without touching global
singletons.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ixse.api.state import FleetState, StateError
from ixse.client import ClientError, RestPyClient
from ixse.models import ServerEntry, Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: object) -> dict:
    return {"status": "ok", "data": data, "timestamp": _now_iso()}


def _session_dict(session: Session) -> dict:
    return session.model_dump(mode="json")


def _default_ixnetwork_web_panel() -> dict:
    return {
        "ixnetwork_web_deployment": None,
        "ixnetwork_web_heartbeat": "yellow",
        "ixnetwork_web_auth_path": None,
        "ixnetwork_web_detail": "Not probed yet — run a poll cycle.",
        "ixnetwork_web_checked_at": None,
        "ixnetwork_version": None,
    }


def _ixnetwork_web_panel_from_state(raw: object) -> dict:
    if not isinstance(raw, dict):
        return _default_ixnetwork_web_panel()
    return {
        "ixnetwork_web_deployment": raw.get("deployment"),
        "ixnetwork_web_heartbeat": raw.get("heartbeat", "yellow"),
        "ixnetwork_web_auth_path": raw.get("auth_path"),
        "ixnetwork_web_detail": raw.get("detail"),
        "ixnetwork_web_checked_at": raw.get("checked_at"),
        "ixnetwork_version": raw.get("ixnetwork_version"),
    }


class TagsUpdateRequest(BaseModel):
    """Body for PATCH /sessions/{server}/{id}/tags."""

    add: list[str] = Field(default_factory=list, description="Tags to add")
    remove: list[str] = Field(default_factory=list, description="Tags to remove")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", summary="List all sessions")
async def list_sessions(
    request: Request,
    server: Optional[str] = Query(None, description="Filter by IxNetwork server name"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
) -> dict:
    """Return all sessions grouped by server.

    Each server row includes IxNetwork Web probe fields (filled after a poll cycle):

    - ``ixnetwork_web_deployment``: ``standalone`` | ``onChassis`` | null
    - ``ixnetwork_web_heartbeat``: ``green`` | ``yellow`` | ``red``
    - ``ixnetwork_web_auth_path``, ``ixnetwork_web_detail``, ``ixnetwork_web_checked_at``

    Response shape::

        {
            "servers": [
                {
                    "name": "ixnet-server-01",
                    "host": "10.0.0.1",
                    "sessions": [...],
                    "session_count": 3,
                    "ixnetwork_web_deployment": "standalone",
                    "ixnetwork_web_heartbeat": "green",
                    ...
                }
            ]
        }

    Optional query params:
    - ``?server=X`` — only include sessions from that server
    - ``?tag=bgp``  — only include sessions carrying that tag
    """
    fleet: FleetState = request.app.state.fleet

    sessions = fleet.get_sessions(server=server)
    if tag is not None:
        sessions = [s for s in sessions if tag in s.tags]

    db_list: list[ServerEntry] = fleet.list_servers()
    host_by_name: dict[str, str] = {e.name: e.host for e in db_list}

    if server is not None:
        server_names_ordered = [server]
    else:
        server_names_ordered = [e.name for e in db_list]

    sessions_by_server: dict[str, list[Session]] = {name: [] for name in server_names_ordered}
    for sess in sessions:
        if sess.ixnet_server not in sessions_by_server:
            sessions_by_server[sess.ixnet_server] = []
        sessions_by_server[sess.ixnet_server].append(sess)

    web_by: dict = getattr(request.app.state, "ixnetwork_web_status", {}) or {}
    poll_errors: dict = getattr(request.app.state, "poll_errors", {}) or {}

    servers_payload = []
    for name, slist in sessions_by_server.items():
        row = {
            "name": name,
            "host": host_by_name.get(name, name),
            "sessions": [_session_dict(s) for s in slist],
            "session_count": len(slist),
            "poll_error": poll_errors.get(name),  # None when last poll succeeded
        }
        row.update(_ixnetwork_web_panel_from_state(web_by.get(name)))
        servers_payload.append(row)

    return _ok({"servers": servers_payload})


@router.get("/{server}/{session_id}", summary="Get session detail")
async def get_session_detail(request: Request, server: str, session_id: str) -> dict:
    """Return full detail for a single session including ports, plane status, and tags."""
    fleet: FleetState = request.app.state.fleet
    session = fleet.get_session(server, session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' on server '{server}' not found.",
        )
    return _ok(_session_dict(session))


@router.patch("/{server}/{session_id}/tags", summary="Update session tags")
async def update_session_tags(
    request: Request,
    server: str,
    session_id: str,
    body: TagsUpdateRequest,
) -> dict:
    """Add and/or remove tags on a session.

    Both *add* and *remove* lists are applied atomically (add first, then
    remove).  Either list may be empty.  Operations are idempotent.
    """
    fleet: FleetState = request.app.state.fleet
    try:
        # Verify session exists before any mutation
        if fleet.get_session(server, session_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' on server '{server}' not found.",
            )
        session = fleet.get_session(server, session_id)
        for tag in body.add:
            session = fleet.add_tag(server, session_id, tag)
        for tag in body.remove:
            session = fleet.remove_tag(server, session_id, tag)
        return _ok(_session_dict(session))  # type: ignore[arg-type]
    except StateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{server}/{session_id}", summary="Kill (destroy) a session")
async def delete_session(
    request: Request,
    server: str,
    session_id: str,
    confirm: bool = Query(False, description="Must be true to confirm deletion"),
) -> dict:
    """Remove a session from IxNetwork and evict it from the state store.

    Requires ``?confirm=true`` as a safety guard against accidental deletion.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm session deletion.",
        )

    fleet: FleetState = request.app.state.fleet

    session = fleet.get_session(server, session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' on server '{server}' not found.",
        )

    server_cfg = fleet.get_server(server)
    if server_cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server}' not found in configuration.",
        )

    def _kill() -> None:
        client = RestPyClient(server_cfg.host, server_cfg.username, server_cfg.password, server_cfg.rest_port)
        client.connect()
        try:
            client.kill_session(session_id)
        finally:
            client.disconnect()

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _kill)
    except ClientError as exc:
        logger.error("Failed to kill session '%s' on '%s': %s", session_id, server, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        fleet.delete_session(server, session_id)
    except StateError:
        pass  # Already evicted (e.g. by a concurrent poll) — safe to ignore

    return _ok({"message": f"Session '{session_id}' on server '{server}' deleted."})


@router.post("/{server}/{session_id}/collect-logs", summary="Collect diagnostic logs")
async def collect_session_logs(
    request: Request,
    server: str,
    session_id: str,
) -> FileResponse:
    """Trigger IxNetwork log collection for a session and return the zip file.

    Calls ``IxNetwork.CollectLogs`` on the server, downloads the resulting
    ``diagnostic_logs.zip``, and streams it back to the caller as a file
    attachment.  The temporary file is cleaned up after the response is sent.
    """
    fleet: FleetState = request.app.state.fleet

    if fleet.get_session(server, session_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' on server '{server}' not found.",
        )

    server_cfg = fleet.get_server(server)
    if server_cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server}' not found in configuration.",
        )

    tmpdir = tempfile.mkdtemp(prefix="ixse_logs_")
    zip_path: str | None = None

    def _collect() -> str:
        client = RestPyClient(
            server_cfg.host, server_cfg.username, server_cfg.password, server_cfg.rest_port
        )
        client.connect()
        try:
            return client.collect_logs_to_file(session_id, tmpdir)
        finally:
            client.disconnect()

    loop = asyncio.get_event_loop()
    try:
        zip_path = await loop.run_in_executor(None, _collect)
    except ClientError as exc:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.error(
            "Log collection failed for session '%s' on '%s': %s", session_id, server, exc
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    def _cleanup() -> None:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{server}_{session_id}")
    download_name = f"diagnostic_logs_{safe_name}.zip"

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=download_name,
        background=BackgroundTask(_cleanup),
    )
