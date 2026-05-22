#!/usr/bin/env python3
"""
MCP Server for IxNetwork Session Explorer (IxNSE).

Provides tools to inspect and manage IxNetwork sessions, servers, chassis,
and poller configuration via the IxNSE REST API.

Configuration:
    IXNSE_API_URL  — Base URL of the IxNSE backend (default: http://localhost:8080)
"""

import json
import os
import tempfile
from contextvars import ContextVar
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mutable container so main() can update the startup default without `global` mutation of a str.
_backend_config: list[str] = [os.environ.get("IXNSE_API_URL", "http://localhost:8080").rstrip("/")]
_backend_url: ContextVar[str] = ContextVar("backend_url")
CHARACTER_LIMIT = 25_000
DEFAULT_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

mcp = FastMCP("ixnse_mcp")


@mcp.custom_route("/", methods=["GET"])
async def health(request: Any) -> Any:
    from starlette.responses import JSONResponse
    return JSONResponse({
        "service": "ixnse-mcp",
        "status": "ok",
        "mcp_endpoint": "/mcp",
        "default_backend": _backend_config[0],
        "backend_override": "append ?backend=<url> to /mcp URL to override per-session",
    })


class BackendURLMiddleware:
    """Pure ASGI middleware — extracts ?backend= query param and sets ContextVar per request.

    Uses raw ASGI interface (not BaseHTTPMiddleware) to avoid response buffering,
    which would break MCP's SSE/chunked streaming transport.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            query_string = scope.get("query_string", b"")
            params = parse_qs(query_string.decode())
            backend_values = params.get("backend", [])
            if backend_values:
                token = _backend_url.set(backend_values[0].rstrip("/"))
                try:
                    await self.app(scope, receive, send)
                finally:
                    _backend_url.reset(token)
                return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


async def _api(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    stream: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Single entry-point for all IxNSE API calls."""
    url = f"{_backend_url.get(_backend_config[0])}{path}"
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            url,
            params=params,
            json=json_body,
            timeout=timeout,
        )
        response.raise_for_status()
        if stream:
            return response.content  # raw bytes
        return response.json()


def _err(e: Exception) -> str:
    """Translate HTTP / network errors into actionable messages."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        if code == 404:
            return f"Error 404: Resource not found. Detail: {detail}"
        if code == 409:
            return f"Error 409: Conflict. Detail: {detail}"
        if code == 422:
            return f"Error 422: Validation error. Detail: {detail}"
        return f"Error {code}: {detail}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. The IxNSE server may be slow or unreachable."
    if isinstance(e, httpx.ConnectError):
        return (
            f"Error: Cannot connect to IxNSE at {_backend_url.get(_backend_config[0])}. "
            "Check IXNSE_API_URL and ensure the server is running."
        )
    return f"Error: {type(e).__name__}: {e}"


def _cap(text: str, hint: str = "") -> str:
    """Truncate response text to CHARACTER_LIMIT with a clear message."""
    if len(text) <= CHARACTER_LIMIT:
        return text
    truncated = text[:CHARACTER_LIMIT]
    note = (
        f"\n\n[TRUNCATED — response exceeded {CHARACTER_LIMIT} chars. "
        f"{hint or 'Use filters or pagination to narrow results.'}]"
    )
    return truncated + note


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class ListSessionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    server: Optional[str] = Field(
        default=None,
        description="Filter by IxNetwork server name (e.g. 'ixnet-lab-01'). Omit for all servers.",
    )
    tag: Optional[str] = Field(
        default=None,
        description="Filter by session tag (e.g. 'bgp', 'regression'). Omit for all tags.",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable, 'json' for machine-readable.",
    )


class GetSessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    server: str = Field(..., description="IxNetwork server name (e.g. 'ixnet-lab-01').")
    session_id: str = Field(..., description="Session ID (e.g. '2').")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CheckPortInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    chassis: str = Field(..., description="Chassis hostname or IP (e.g. '10.0.0.5' or 'ixia-chassis-01').")
    card: int = Field(..., ge=1, description="Card number (e.g. 1).")
    port: int = Field(..., ge=1, description="Port number (e.g. 3).")


class KillSessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    server: str = Field(..., description="IxNetwork server name owning the session.")
    session_id: str = Field(..., description="Session ID to destroy.")
    confirm: bool = Field(
        ...,
        description=(
            "Must be True to confirm destruction. "
            "This permanently removes the IxNetwork session. "
            "Set to True only after user confirmation."
        ),
    )


class UpdateSessionTagsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    server: str = Field(..., description="IxNetwork server name.")
    session_id: str = Field(..., description="Session ID.")
    add: List[str] = Field(default_factory=list, description="Tags to add (e.g. ['bgp', 'nightly']).")
    remove: List[str] = Field(default_factory=list, description="Tags to remove (e.g. ['old-tag']).")


class CollectLogsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    server: str = Field(..., description="IxNetwork server name.")
    session_id: str = Field(..., description="Session ID to collect logs from.")
    save_path: Optional[str] = Field(
        default=None,
        description=(
            "Local filesystem path to save the zip file "
            "(e.g. '/tmp/ixn_logs.zip'). "
            "Defaults to a temp file if omitted."
        ),
    )


class ListChassisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ServerNameInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="IxNetwork server name as registered in IxNSE.")


class AddServerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Unique name for this server (e.g. 'ixnet-lab-01').")
    host: str = Field(..., description="Hostname or IP of the IxNetwork REST server.")
    username: str = Field(..., description="Login username.")
    password: str = Field(..., description="Login password.")
    rest_port: Optional[int] = Field(default=None, description="REST API port (default 443 for HTTPS).")
    tags: List[str] = Field(default_factory=list, description="Optional tags (e.g. ['lab', 'bgp']).")


class UpdateServerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Server name to update.")
    host: Optional[str] = Field(default=None, description="New hostname or IP.")
    username: Optional[str] = Field(default=None, description="New username.")
    password: Optional[str] = Field(default=None, description="New password.")
    rest_port: Optional[int] = Field(default=None, description="New REST port.")
    tags: Optional[List[str]] = Field(default=None, description="Replace full tag list.")


class DeleteServerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Server name to remove from IxNSE.")


class BulkUpsertServerEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str
    host: str
    username: str
    password: str
    rest_port: Optional[int] = None
    tags: List[str] = Field(default_factory=list)


class BulkUpsertInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: List[BulkUpsertServerEntry] = Field(
        ..., description="List of server definitions to add/update atomically."
    )


class BulkDeleteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    names: List[str] = Field(..., description="List of server names to delete.")


class BulkPasswordInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    names: List[str] = Field(..., description="Server names to update.")
    password: str = Field(..., description="New password to apply to all named servers.")


class UpdateServerTagsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Server name.")
    add: List[str] = Field(default_factory=list, description="Tags to add.")
    remove: List[str] = Field(default_factory=list, description="Tags to remove.")


class ProbeServerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    host: str = Field(..., description="Hostname or IP to probe.")
    username: str = Field(..., description="Login username.")
    password: str = Field(..., description="Login password.")
    rest_port: int = Field(default=443, description="REST API port (default 443).")


class UpdatePollIntervalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: int = Field(..., ge=10, description="New poll interval in seconds (minimum 10).")


# ---------------------------------------------------------------------------
# Tools — Sessions
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ixnse_list_sessions",
    annotations={
        "title": "List IxNetwork Sessions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_list_sessions(params: ListSessionsInput) -> str:
    """List all IxNetwork sessions known to IxNSE, grouped by server.

    Returns session metadata including CP/DP plane activity, port assignments,
    tags, and server-level IxNetwork Web heartbeat status.

    Args:
        params (ListSessionsInput):
            - server (Optional[str]): Filter to a single server name.
            - tag (Optional[str]): Filter to sessions carrying this tag.
            - response_format: 'markdown' (default) or 'json'.

    Returns:
        str: Session list grouped by server. Each session shows:
            id, name, owner, cp_active, dp_active, utilized, tags, ports.

    Examples:
        - "Show all active sessions" → no filters, markdown
        - "Which sessions on ixnet-lab-01 are utilizing ports?" → server='ixnet-lab-01'
        - "Find BGP sessions" → tag='bgp'
    """
    try:
        q: Dict[str, Any] = {}
        if params.server:
            q["server"] = params.server
        if params.tag:
            q["tag"] = params.tag
        data = await _api("GET", "/sessions/", params=q or None)

        if params.response_format == ResponseFormat.JSON:
            return _cap(json.dumps(data, indent=2), "Filter by server= or tag=.")

        servers = data.get("servers", [])
        if not servers:
            return "No sessions found."

        lines: List[str] = []
        for srv in servers:
            lines.append(f"## Server: {srv['name']} ({srv.get('host', '')})")
            heartbeat = srv.get("ixnetwork_web_heartbeat")
            if heartbeat:
                lines.append(f"IxNetwork Web: {heartbeat} ({srv.get('ixnetwork_web_deployment', 'unknown')})")
            sessions = srv.get("sessions", [])
            if not sessions:
                lines.append("  _No sessions_")
            for s in sessions:
                utilized = "YES" if s.get("utilized") else "no"
                cp = "UP" if s.get("cp_active") else "-"
                dp = "UP" if s.get("dp_active") else "-"
                tags = ", ".join(s.get("tags", [])) or "-"
                lines.append(
                    f"  [{s['id']}] {s.get('name', '(unnamed)')} | owner={s.get('username', '?')} "
                    f"| CP={cp} DP={dp} | utilized={utilized} | tags={tags}"
                )
                for port in s.get("ports", []):
                    fqn = port.get("fully_qualified_port_name") or f"{port.get('chassis','?')}/{port.get('card','?')}/{port.get('port','?')}"
                    lines.append(f"      port: {fqn} | cp={port.get('cp_active')} dp={port.get('dp_active')}")
            lines.append("")

        return _cap("\n".join(lines), "Filter by server= or tag= to narrow results.")
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_get_session",
    annotations={
        "title": "Get IxNetwork Session Detail",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_get_session(params: GetSessionInput) -> str:
    """Return full detail for a single IxNetwork session including ports, plane status, and tags.

    Args:
        params (GetSessionInput):
            - server (str): Server name (e.g. 'ixnet-lab-01').
            - session_id (str): Session ID (e.g. '2').
            - response_format: 'markdown' or 'json'.

    Returns:
        str: Full session detail — id, name, owner, ports with chassis/card/port,
             CP/DP status per port, LLDP neighbors, errors, tags.
    """
    try:
        data = await _api("GET", f"/sessions/{params.server}/{params.session_id}")

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)

        s = data
        lines = [
            f"# Session {s['id']} — {s.get('name', '(unnamed)')}",
            f"Server: {params.server}",
            f"Owner: {s.get('username', '?')}",
            f"CP active: {s.get('cp_active')} | DP active: {s.get('dp_active')} | Utilized: {s.get('utilized')}",
            f"Tags: {', '.join(s.get('tags', [])) or 'none'}",
            "",
            "## Ports",
        ]
        for p in s.get("ports", []):
            fqn = p.get("fully_qualified_port_name") or f"{p.get('chassis')}/{p.get('card')}/{p.get('port')}"
            lines.append(f"- {fqn} | CP={p.get('cp_active')} DP={p.get('dp_active')}")
            if p.get("lldp_neighbors"):
                for n in p["lldp_neighbors"]:
                    lines.append(f"    LLDP: {n}")

        errors = s.get("errors", [])
        if errors:
            lines.append("\n## Errors")
            for err in errors:
                lines.append(f"- {err}")

        return "\n".join(lines)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_check_port_utilized",
    annotations={
        "title": "Check If Physical Port Is In Use",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_check_port_utilized(params: CheckPortInput) -> str:
    """Check whether a specific physical chassis/card/port is actively utilized (CP or DP active).

    Scans all known sessions for a matching port assignment. Returns utilized=false
    if the port is not assigned to any session.

    Args:
        params (CheckPortInput):
            - chassis (str): Chassis hostname or IP (e.g. '10.0.0.5').
            - card (int): Card number (e.g. 1).
            - port (int): Port number (e.g. 3).

    Returns:
        str: Utilization status — utilized bool, cp_active, dp_active,
             and which session owns the port (if any).

    Examples:
        - "Is port 2/1 on 10.0.0.5 in use?" → chassis='10.0.0.5', card=2, port=1
    """
    try:
        data = await _api("GET", f"/sessions/ports/{params.chassis}/{params.card}/{params.port}/utilized")
        utilized = data.get("utilized", False)
        status = "IN USE" if utilized else "FREE"
        lines = [
            f"Port {params.chassis}/{params.card}/{params.port}: **{status}**",
            f"  CP active: {data.get('cp_active', False)}",
            f"  DP active: {data.get('dp_active', False)}",
        ]
        if data.get("session_id"):
            lines.append(f"  Owned by session: {data.get('server')}/{data.get('session_id')}")
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_kill_session",
    annotations={
        "title": "Kill (Destroy) IxNetwork Session",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ixnse_kill_session(params: KillSessionInput) -> str:
    """Permanently destroy an IxNetwork session and release its resources.

    Removes the session from IxNetwork and evicts it from IxNSE state.
    This is irreversible — all test configuration in the session is lost.

    Args:
        params (KillSessionInput):
            - server (str): Server name owning the session.
            - session_id (str): Session ID to destroy.
            - confirm (bool): Must be True. Require explicit user confirmation before setting.

    Returns:
        str: Confirmation message or error.

    Error Handling:
        - confirm=False → returns error message, nothing is deleted
        - 404 → session not found (may have already been killed)
    """
    if not params.confirm:
        return (
            "Error: confirm must be True to destroy a session. "
            "This operation is irreversible — all session data will be lost. "
            "Obtain explicit user confirmation before retrying."
        )
    try:
        data = await _api(
            "DELETE",
            f"/sessions/{params.server}/{params.session_id}",
            params={"confirm": "true"},
        )
        return f"Session {params.server}/{params.session_id} killed. Response: {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_update_session_tags",
    annotations={
        "title": "Update IxNetwork Session Tags",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_update_session_tags(params: UpdateSessionTagsInput) -> str:
    """Add and/or remove tags on an IxNetwork session atomically.

    Tags persist across poll cycles. Both add and remove lists are applied
    in order (add first, then remove). Operations are idempotent.

    Args:
        params (UpdateSessionTagsInput):
            - server (str): Server name.
            - session_id (str): Session ID.
            - add (List[str]): Tags to add (e.g. ['bgp', 'nightly']).
            - remove (List[str]): Tags to remove (e.g. ['old-tag']).

    Returns:
        str: Updated tag list or error.
    """
    try:
        data = await _api(
            "PATCH",
            f"/sessions/{params.server}/{params.session_id}/tags",
            json_body={"add": params.add, "remove": params.remove},
        )
        tags = data.get("tags", [])
        return f"Tags updated. Current tags: {tags}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_collect_session_logs",
    annotations={
        "title": "Collect IxNetwork Session Diagnostic Logs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ixnse_collect_session_logs(params: CollectLogsInput) -> str:
    """Trigger IxNetwork log collection for a session and download the diagnostic zip.

    Calls IxNetwork.CollectLogs on the server, downloads the resulting zip,
    and saves it locally. This may take 30-120 seconds for large sessions.

    Args:
        params (CollectLogsInput):
            - server (str): Server name.
            - session_id (str): Session ID.
            - save_path (Optional[str]): Local path for zip file. Auto-generated if omitted.

    Returns:
        str: Path to saved zip file and its size, or error message.
    """
    try:
        raw = await _api(
            "POST",
            f"/sessions/{params.server}/{params.session_id}/collect-logs",
            stream=True,
            timeout=180.0,
        )
        if params.save_path:
            path = params.save_path
        else:
            fd, path = tempfile.mkstemp(suffix=".zip", prefix=f"ixn_logs_{params.server}_{params.session_id}_")
            os.close(fd)
        with open(path, "wb") as f:
            f.write(raw)
        size_kb = len(raw) / 1024
        return f"Logs saved to: {path} ({size_kb:.1f} KB)"
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Tools — Chassis
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ixnse_list_chassis",
    annotations={
        "title": "List All Chassis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_list_chassis(params: ListChassisInput) -> str:
    """Return all chassis known to IxNSE, derived from session port assignments.

    Args:
        params (ListChassisInput):
            - response_format: 'markdown' or 'json'.

    Returns:
        str: List of chassis names/IPs seen across all sessions.
    """
    try:
        data = await _api("GET", "/chassis/")
        if params.response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)
        chassis_list = data.get("chassis", [])
        if not chassis_list:
            return "No chassis found. Run a poll cycle first."
        lines = ["# Chassis List", ""]
        for c in chassis_list:
            lines.append(f"- {c}")
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_get_chassis_health",
    annotations={
        "title": "Get Chassis Health Detail",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_get_chassis_health(params: ServerNameInput) -> str:
    """Return health details for a single chassis by name.

    Note: Live IxOS reachability checks are a future milestone.
    Currently returns 404 until chassis config support is implemented.

    Args:
        params (ServerNameInput):
            - name (str): Chassis name or hostname.

    Returns:
        str: Health detail or 404 if chassis health is not yet implemented.
    """
    try:
        data = await _api("GET", f"/chassis/{params.name}/health")
        return json.dumps(data, indent=2)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Tools — Fleet Health
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ixnse_fleet_health",
    annotations={
        "title": "Get Fleet Health Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_fleet_health() -> str:
    """Return a fleet-wide health summary for all IxNSE-managed servers.

    Returns:
        str: Fleet health envelope with per-server reachability status.
    """
    try:
        data = await _api("GET", "/health/")
        return json.dumps(data, indent=2)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Tools — Servers
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ixnse_list_servers",
    annotations={
        "title": "List Configured IxNetwork Servers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_list_servers(response_format: ResponseFormat = ResponseFormat.MARKDOWN) -> str:
    """List all IxNetwork servers registered in IxNSE (names, hosts, ports, tags).

    Passwords are never returned by the API.

    Args:
        response_format: 'markdown' (default) or 'json'.

    Returns:
        str: Server list with name, host, rest_port, tags, last poll status.
    """
    try:
        data = await _api("GET", "/servers/")
        if response_format == ResponseFormat.JSON:
            return json.dumps(data, indent=2)
        servers = data.get("servers", [])
        if not servers:
            return "No servers configured. Use ixnse_add_server to register one."
        lines = ["# Configured IxNetwork Servers", ""]
        for s in servers:
            tags = ", ".join(s.get("tags", [])) or "none"
            lines.append(
                f"- **{s['name']}** — host={s['host']} port={s.get('rest_port', 443)} tags=[{tags}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_add_server",
    annotations={
        "title": "Add IxNetwork Server",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ixnse_add_server(params: AddServerInput) -> str:
    """Register a new IxNetwork server in IxNSE for polling.

    Args:
        params (AddServerInput):
            - name (str): Unique server name (e.g. 'ixnet-lab-01').
            - host (str): Hostname or IP.
            - username (str): Login username.
            - password (str): Login password.
            - rest_port (Optional[int]): REST port (default 443).
            - tags (List[str]): Optional tags.

    Returns:
        str: Success message with server name, or error if name already exists.
    """
    try:
        body = params.model_dump(exclude_none=True)
        data = await _api("POST", "/servers/", json_body=body)
        return f"Server '{params.name}' added. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_update_server",
    annotations={
        "title": "Update IxNetwork Server",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_update_server(params: UpdateServerInput) -> str:
    """Update host, credentials, port, or tags for an existing IxNetwork server.

    Only supply fields you want to change — omit fields to leave them unchanged.

    Args:
        params (UpdateServerInput):
            - name (str): Server to update.
            - host, username, password, rest_port, tags: Fields to update (all optional).

    Returns:
        str: Updated server record or error.
    """
    try:
        body = {k: v for k, v in params.model_dump().items() if k != "name" and v is not None}
        data = await _api("PUT", f"/servers/{params.name}", json_body=body)
        return f"Server '{params.name}' updated. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_delete_server",
    annotations={
        "title": "Delete IxNetwork Server",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ixnse_delete_server(params: DeleteServerInput) -> str:
    """Remove an IxNetwork server from IxNSE. Does NOT kill any sessions.

    Args:
        params (DeleteServerInput):
            - name (str): Server name to remove.

    Returns:
        str: Confirmation or error.
    """
    try:
        data = await _api("DELETE", f"/servers/{params.name}")
        return f"Server '{params.name}' removed. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_bulk_upsert_servers",
    annotations={
        "title": "Bulk Add/Update IxNetwork Servers",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_bulk_upsert_servers(params: BulkUpsertInput) -> str:
    """Add new servers and update existing ones in a single atomic request.

    Each entry returns action='created' | 'updated' | 'error'.

    Args:
        params (BulkUpsertInput):
            - servers (List): List of server definitions (name, host, username, password, rest_port, tags).

    Returns:
        str: Per-server action results.
    """
    try:
        body = {"servers": [s.model_dump(exclude_none=True) for s in params.servers]}
        data = await _api("POST", "/servers/bulk", json_body=body)
        results = data.get("results", [])
        lines = [f"Bulk upsert: {len(results)} server(s) processed."]
        for r in results:
            lines.append(f"  {r.get('name')}: {r.get('action')}")
            if r.get("error"):
                lines.append(f"    Error: {r['error']}")
        return "\n".join(lines)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_bulk_delete_servers",
    annotations={
        "title": "Bulk Delete IxNetwork Servers",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ixnse_bulk_delete_servers(params: BulkDeleteInput) -> str:
    """Delete multiple IxNetwork servers by name in a single request.

    Args:
        params (BulkDeleteInput):
            - names (List[str]): Server names to delete.

    Returns:
        str: Deletion result summary.
    """
    try:
        data = await _api("DELETE", "/servers/bulk", json_body={"names": params.names})
        return f"Bulk delete result: {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_bulk_update_password",
    annotations={
        "title": "Bulk Update Server Password",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_bulk_update_password(params: BulkPasswordInput) -> str:
    """Set a new password for multiple IxNetwork servers at once.

    Useful after a lab-wide password rotation.

    Args:
        params (BulkPasswordInput):
            - names (List[str]): Server names to update.
            - password (str): New password.

    Returns:
        str: Per-server update result.
    """
    try:
        data = await _api(
            "PATCH",
            "/servers/bulk/password",
            json_body={"names": params.names, "password": params.password},
        )
        return f"Password updated for {len(params.names)} server(s). {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_update_server_tags",
    annotations={
        "title": "Update IxNetwork Server Tags",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_update_server_tags(params: UpdateServerTagsInput) -> str:
    """Add and/or remove tags on an IxNetwork server. Both lists are applied atomically.

    Args:
        params (UpdateServerTagsInput):
            - name (str): Server name.
            - add (List[str]): Tags to add.
            - remove (List[str]): Tags to remove.

    Returns:
        str: Updated tag list.
    """
    try:
        data = await _api(
            "PATCH",
            f"/servers/{params.name}/tags",
            json_body={"add": params.add, "remove": params.remove},
        )
        tags = data.get("tags", [])
        return f"Server '{params.name}' tags updated: {tags}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_probe_server",
    annotations={
        "title": "Test Server Connectivity (No DB Required)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_probe_server(params: ProbeServerInput) -> str:
    """Test IxNetwork server connectivity with supplied credentials without saving to DB.

    Useful for validating credentials before registering a server.

    Args:
        params (ProbeServerInput):
            - host (str): Hostname or IP.
            - username (str): Login username.
            - password (str): Login password.
            - rest_port (int): REST port (default 443).

    Returns:
        str: 'ok' with latency or error detail if connection fails.
    """
    try:
        data = await _api(
            "POST",
            "/servers/probe",
            json_body={
                "host": params.host,
                "username": params.username,
                "password": params.password,
                "rest_port": params.rest_port,
            },
        )
        return json.dumps(data, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_test_server",
    annotations={
        "title": "Test Connectivity to Registered Server",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_test_server(params: ServerNameInput) -> str:
    """Test connectivity to a registered IxNetwork server using its stored credentials.

    Args:
        params (ServerNameInput):
            - name (str): Server name as registered in IxNSE.

    Returns:
        str: Connection test result — ok/error with detail.
    """
    try:
        data = await _api("POST", f"/servers/{params.name}/test")
        return json.dumps(data, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_probe_kcos",
    annotations={
        "title": "Re-Run KCOS SSH Detection Probe",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_probe_kcos(params: ServerNameInput) -> str:
    """Trigger the KCOS SSH banner probe for a server in the background.

    Use ixnse_probe_kcos_debug for synchronous full debug output.
    The updated kcos_info will appear on the next poll/refresh cycle.

    Args:
        params (ServerNameInput):
            - name (str): Server name.

    Returns:
        str: Acknowledgement that probe was triggered (result is async).
    """
    try:
        data = await _api("POST", f"/servers/{params.name}/probe-kcos")
        return f"KCOS probe triggered for '{params.name}'. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_probe_kcos_debug",
    annotations={
        "title": "Run KCOS SSH Probe (Synchronous Debug)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_probe_kcos_debug(params: ServerNameInput) -> str:
    """Run KCOS SSH banner probe synchronously and return full diagnostic detail.

    Shows: SSH connectivity, raw MOTD received, whether KCOS marker was found,
    and error message if SSH failed. Persists result — kcos_cache updated immediately.

    Args:
        params (ServerNameInput):
            - name (str): Server name.

    Returns:
        str: Full KCOS probe debug output including SSH result and MOTD.
    """
    try:
        data = await _api("POST", f"/servers/{params.name}/probe-kcos-debug")
        return json.dumps(data, indent=2)
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_probe_web",
    annotations={
        "title": "Debug IxNetwork Web HTTPS Auth Probe",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_probe_web(params: ServerNameInput) -> str:
    """Run the IxNetwork Web HTTPS auth probe immediately with full debug detail.

    Shows URLs tried, HTTP status codes, whether an apiKey was received,
    and which deployment type was detected. Use when heartbeat shows yellow/red.

    Args:
        params (ServerNameInput):
            - name (str): Server name.

    Returns:
        str: Probe detail including deployment type and auth path found.
    """
    try:
        data = await _api("POST", f"/servers/{params.name}/probe-web")
        return json.dumps(data, indent=2)
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Tools — Poller
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ixnse_poll_status",
    annotations={
        "title": "Get Poller Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ixnse_poll_status() -> str:
    """Return the current background poller state.

    Returns:
        str: last_polled_at (UTC), next_scheduled (UTC), is_polling (bool).

    Examples:
        - "When was the last poll?" → check last_polled_at
        - "Is a poll cycle running now?" → check is_polling
    """
    try:
        data = await _api("GET", "/poll/status")
        return (
            f"Last polled: {data.get('last_polled_at', 'never')}\n"
            f"Next scheduled: {data.get('next_scheduled', 'unknown')}\n"
            f"Polling now: {data.get('is_polling', False)}"
        )
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_poll_config",
    annotations={
        "title": "Get Poll Interval Configuration",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ixnse_poll_config() -> str:
    """Return the current poll interval configuration.

    Returns:
        str: Current interval_seconds value.
    """
    try:
        data = await _api("GET", "/poll/config")
        return f"Poll interval: {data.get('interval_seconds')} seconds"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_trigger_poll",
    annotations={
        "title": "Force Immediate Poll Cycle",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def ixnse_trigger_poll() -> str:
    """Kick off a poll cycle immediately without waiting for the next scheduled interval.

    Use when session data looks stale and you need fresh state now.

    Returns:
        str: Acknowledgement that poll was triggered.
    """
    try:
        data = await _api("POST", "/poll/trigger")
        return f"Poll triggered. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


@mcp.tool(
    name="ixnse_update_poll_interval",
    annotations={
        "title": "Update Poll Interval",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def ixnse_update_poll_interval(params: UpdatePollIntervalInput) -> str:
    """Change how often IxNSE polls all registered IxNetwork servers.

    The new interval is persisted to SQLite and survives restarts.

    Args:
        params (UpdatePollIntervalInput):
            - interval_seconds (int): New poll interval in seconds (minimum 10).

    Returns:
        str: Confirmation with new interval value.
    """
    try:
        data = await _api("PATCH", "/poll/config", json_body={"interval_seconds": params.interval_seconds})
        return f"Poll interval updated to {params.interval_seconds}s. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Tools — Admin
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ixnse_clear_cache",
    annotations={
        "title": "Clear KCOS and IxNetwork-Web Detection Caches",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ixnse_clear_cache() -> str:
    """Clear KCOS SSH detection cache and IxNetwork Web status cache.

    Re-fires KCOS SSH probes for every registered server in the background.
    Updated detection results appear on the next refresh cycle.

    Use when server detection looks wrong after a software upgrade or reconfiguration.

    Returns:
        str: Confirmation of cache clear and re-probe trigger.
    """
    try:
        data = await _api("POST", "/admin/clear-cache")
        return f"Cache cleared and KCOS probes re-fired. {json.dumps(data)}"
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse
    import asyncio
    import uvicorn

    parser = argparse.ArgumentParser(description="IxNSE MCP Server (streamable-HTTP)")
    parser.add_argument(
        "--api-url",
        default=None,
        help="IxNSE backend base URL (overrides IXNSE_API_URL env var)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8889, help="Bind port (default: 8889)")
    args = parser.parse_args()

    if args.api_url:
        _backend_config[0] = args.api_url.rstrip("/")

    app = mcp.streamable_http_app()
    app.add_middleware(BackendURLMiddleware)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
