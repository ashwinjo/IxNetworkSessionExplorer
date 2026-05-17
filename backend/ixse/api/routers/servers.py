"""
Servers endpoints: CRUD + bulk operations for IxNetwork server configurations.

Single:
  GET    /servers              — list all servers (password masked)
  POST   /servers              — add a new server
  PUT    /servers/{name}       — update an existing server
  PATCH  /servers/{name}/tags  — add/remove tags on a server
  DELETE /servers/{name}       — remove a server
  POST   /servers/{name}/test  — test connectivity to a server

Bulk:
  POST   /servers/bulk           — upsert a list of servers (add new, update existing)
  DELETE /servers/bulk           — delete a list of servers by name
  PATCH  /servers/bulk/password  — set a new password for a list of servers
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ixse.api.state import FleetState, StateError
from ixse.models import KcosInfo, ServerEntry, ServerEntryPublic

router = APIRouter(prefix="/servers", tags=["servers"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public(entry: ServerEntry) -> dict:
    return ServerEntryPublic(
        name=entry.name,
        host=entry.host,
        username=entry.username,
        rest_port=entry.rest_port,
        tags=entry.tags,
        kcos_info=entry.kcos_info,
    ).model_dump()


async def _run_kcos_probe(fleet: FleetState, entry: ServerEntry) -> None:
    """Run the KCOS SSH probe in a thread and persist the result."""
    from ixse.kcos import probe_kcos

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, probe_kcos, entry.host, entry.username, entry.password
    )
    fleet.update_kcos_info(entry.host, KcosInfo(**result) if result else None)


# ---------------------------------------------------------------------------
# Request body schemas
# ---------------------------------------------------------------------------


class ServerCreateRequest(BaseModel):
    name: str
    host: str
    username: str
    password: str
    rest_port: int | None = None
    tags: list[str] = []


class ServerUpdateRequest(BaseModel):
    host: str | None = None
    username: str | None = None
    password: str | None = None
    rest_port: int | None = None
    tags: list[str] | None = None


class TagsUpdateRequest(BaseModel):
    """Body for PATCH /servers/{name}/tags."""

    add: list[str] = Field(default_factory=list, description="Tags to add")
    remove: list[str] = Field(default_factory=list, description="Tags to remove")


class BulkUpsertRequest(BaseModel):
    servers: list[ServerCreateRequest]


class BulkDeleteRequest(BaseModel):
    names: list[str]


class BulkPasswordRequest(BaseModel):
    names: list[str]
    password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/bulk", summary="Bulk upsert servers (add new, update existing)")
async def bulk_upsert_servers(body: BulkUpsertRequest, request: Request) -> dict:
    """Accept a list of server definitions and upsert each one atomically.

    - If a server with that name already exists → update host/username/password/port.
    - If it doesn't exist → create it.
    - Each entry in the response carries an ``action`` field:
      ``"created"`` | ``"updated"`` | ``"error"``.
    """
    entries = []
    validation_errors = []
    for i, s in enumerate(body.servers):
        if not s.name.strip():
            validation_errors.append(f"Row {i+1}: 'name' is required")
        elif not s.host.strip():
            validation_errors.append(f"Row {i+1} ('{s.name}'): 'host' is required")
        elif not s.username.strip():
            validation_errors.append(f"Row {i+1} ('{s.name}'): 'username' is required")
        else:
            entries.append(
                ServerEntry(
                    name=s.name.strip(),
                    host=s.host.strip(),
                    username=s.username.strip(),
                    password=s.password,
                    rest_port=s.rest_port,
                )
            )

    if validation_errors:
        raise HTTPException(status_code=422, detail="; ".join(validation_errors))

    results = request.app.state.fleet.bulk_upsert_servers(entries)
    created = sum(1 for r in results if r["action"] == "created")
    updated = sum(1 for r in results if r["action"] == "updated")
    errors  = sum(1 for r in results if r["action"] == "error")

    return {
        "status": "ok",
        "data": {
            "results": results,
            "summary": {"created": created, "updated": updated, "errors": errors},
        },
        "timestamp": _now_iso(),
    }


@router.delete("/bulk", summary="Bulk delete servers by name")
async def bulk_delete_servers(body: BulkDeleteRequest, request: Request) -> dict:
    """Delete multiple servers by name in a single request."""
    if not body.names:
        raise HTTPException(status_code=422, detail="'names' list must not be empty")

    results = request.app.state.fleet.bulk_delete_servers(body.names)
    deleted   = sum(1 for r in results if r["action"] == "deleted")
    not_found = sum(1 for r in results if r["action"] == "not_found")

    return {
        "status": "ok",
        "data": {
            "results": results,
            "summary": {"deleted": deleted, "not_found": not_found},
        },
        "timestamp": _now_iso(),
    }


@router.patch("/bulk/password", summary="Set a new password for multiple servers")
async def bulk_update_password(body: BulkPasswordRequest, request: Request) -> dict:
    """Change the stored password for each named server."""
    if not body.names:
        raise HTTPException(status_code=422, detail="'names' list must not be empty")
    if not body.password:
        raise HTTPException(status_code=422, detail="'password' must not be empty")

    results = request.app.state.fleet.bulk_update_password(body.names, body.password)
    updated   = sum(1 for r in results if r["action"] == "updated")
    not_found = sum(1 for r in results if r["action"] == "not_found")

    return {
        "status": "ok",
        "data": {
            "results": results,
            "summary": {"updated": updated, "not_found": not_found},
        },
        "timestamp": _now_iso(),
    }


@router.get("/", summary="List all configured IxNetwork servers")
async def list_servers(request: Request) -> dict:
    servers = request.app.state.fleet.list_servers()
    return {
        "status": "ok",
        "data": {"servers": [_public(s) for s in servers]},
        "timestamp": _now_iso(),
    }


@router.post("/", summary="Add a new IxNetwork server", status_code=201)
async def create_server(body: ServerCreateRequest, request: Request) -> dict:
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="'name' must not be empty")
    if not body.host.strip():
        raise HTTPException(status_code=422, detail="'host' must not be empty")
    if not body.username.strip():
        raise HTTPException(status_code=422, detail="'username' must not be empty")

    fleet = request.app.state.fleet
    if fleet.get_server(body.name) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Server '{body.name}' already exists. Use PUT to update.",
        )

    entry = ServerEntry(
        name=body.name.strip(),
        host=body.host.strip(),
        username=body.username.strip(),
        password=body.password,
        rest_port=body.rest_port,
        tags=body.tags,
    )
    fleet.upsert_server(entry)

    # Fire KCOS SSH probe in the background — result persisted when complete.
    asyncio.create_task(_run_kcos_probe(fleet, entry))

    return {
        "status": "ok",
        "data": _public(entry),
        "timestamp": _now_iso(),
    }


@router.put("/{name}", summary="Update an existing IxNetwork server")
async def update_server(name: str, body: ServerUpdateRequest, request: Request) -> dict:
    fleet = request.app.state.fleet
    existing = fleet.get_server(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

    updated = ServerEntry(
        name=existing.name,
        host=body.host.strip() if body.host is not None else existing.host,
        username=body.username.strip() if body.username is not None else existing.username,
        password=body.password if body.password is not None else existing.password,
        rest_port=body.rest_port if body.rest_port is not None else existing.rest_port,
        tags=body.tags if body.tags is not None else existing.tags,
    )
    fleet.upsert_server(updated)

    return {
        "status": "ok",
        "data": _public(updated),
        "timestamp": _now_iso(),
    }


@router.patch("/{name}/tags", summary="Update tags on an IxNetwork server")
async def update_server_tags(name: str, body: TagsUpdateRequest, request: Request) -> dict:
    """Add and/or remove tags on a server.

    Both *add* and *remove* lists are applied in order (add first, then
    remove).  Either list may be empty.  Operations are idempotent.
    """
    fleet = request.app.state.fleet
    if fleet.get_server(name) is None:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    try:
        server = fleet.get_server(name)
        for tag in body.add:
            server = fleet.add_server_tag(name, tag)
        for tag in body.remove:
            server = fleet.remove_server_tag(name, tag)
        return {"status": "ok", "data": _public(server), "timestamp": _now_iso()}  # type: ignore[arg-type]
    except StateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{name}", summary="Remove an IxNetwork server")
async def delete_server(name: str, request: Request) -> dict:
    deleted = request.app.state.fleet.delete_server(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    return {"status": "ok", "message": f"Server '{name}' deleted.", "timestamp": _now_iso()}


@router.post("/{name}/test", summary="Test connectivity to an IxNetwork server")
async def test_server(name: str, request: Request) -> dict:
    """Attempt a quick RestPy connect/disconnect to verify credentials."""
    fleet = request.app.state.fleet
    server = fleet.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

    from ixse.client import RestPyClient

    client = RestPyClient(server.host, server.username, server.password, server.rest_port)
    try:
        client.connect()
        client.disconnect()
        return {
            "status": "ok",
            "message": f"Successfully connected to '{name}' ({server.host})",
            "timestamp": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": str(exc),
            "timestamp": _now_iso(),
        }


@router.post("/{name}/probe-kcos", summary="Re-run KCOS SSH detection probe")
async def probe_server_kcos(name: str, request: Request) -> dict:
    """Trigger the KCOS SSH banner probe for an existing server.

    Runs in the background — the response returns immediately.  The UI will
    reflect the updated kcos_info on the next poll/refresh cycle.
    """
    fleet: FleetState = request.app.state.fleet
    entry = fleet.get_server(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

    asyncio.create_task(_run_kcos_probe(fleet, entry))
    return {"status": "ok", "message": "KCOS probe scheduled", "timestamp": _now_iso()}


@router.post("/{name}/probe-web", summary="Debug IxNetwork Web HTTPS auth probe")
async def probe_web(name: str, request: Request) -> dict:
    """Run the IxNetwork Web HTTPS auth probe immediately and return full debug detail.

    Shows the exact URLs tried, HTTP status codes, whether an apiKey was received,
    and which deployment type was detected.  Useful for diagnosing why heartbeat
    shows yellow/red after adding a server.
    """
    import asyncio

    from ixse.ixn_web import probe_web_verbose

    fleet = request.app.state.fleet
    server = fleet.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, probe_web_verbose, server)

    # Push result into live ixnetwork_web_status so the main UI updates immediately.
    if result.get("checked_at"):
        request.app.state.ixnetwork_web_status[name] = {
            "deployment": result.get("deployment"),
            "heartbeat": result.get("heartbeat", "yellow"),
            "auth_path": None,
            "detail": result.get("detail"),
            "checked_at": result.get("checked_at"),
            "ixnetwork_version": result.get("ixnetwork_version"),
        }

    return {
        "status": "ok",
        "data": result,
        "timestamp": _now_iso(),
    }
