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
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ixse.api.state import FleetState, StateError
from ixse.client import ClientError, RestPyClient
from ixse.models import Session

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
    """Return all sessions, optionally filtered by *server* and/or *tag*."""
    fleet: FleetState = request.app.state.fleet
    sessions = fleet.get_sessions(server=server)
    if tag is not None:
        sessions = [s for s in sessions if tag in s.tags]
    return _ok({"sessions": [_session_dict(s) for s in sessions]})


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
    config = request.app.state.config

    session = fleet.get_session(server, session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' on server '{server}' not found.",
        )

    server_cfg = next(
        (s for s in config.ixnet_servers if s.name == server), None
    )
    if server_cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server}' not found in configuration.",
        )

    def _kill() -> None:
        client = RestPyClient(server_cfg.host, server_cfg.username, server_cfg.password)
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
