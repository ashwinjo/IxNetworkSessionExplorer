# MCP Backend URL Override Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow the IxNSE MCP server's backend API URL to be overridden per-request via a `?backend=` query parameter on the `/mcp` endpoint, so Claude configs can specify it directly in the URL.

**Architecture:** Keep the module-level `_DEFAULT_BACKEND` as a mutable string (set at startup from env/CLI). Add a `ContextVar[str]` that middleware populates from `?backend=` on each request. `_api()` reads the ContextVar with `_DEFAULT_BACKEND` as fallback. The FastMCP Starlette app is wrapped with `BaseHTTPMiddleware` in `main()` and run via uvicorn directly.

**Tech Stack:** Python 3.11+, FastMCP (mcp[cli] ≥1.0), Starlette `BaseHTTPMiddleware`, `contextvars.ContextVar`, uvicorn, httpx, pytest + starlette TestClient for tests.

---

### Task 1: Replace `API_BASE_URL` with `_DEFAULT_BACKEND` + `ContextVar`

**Files:**
- Modify: `mcp/ixnse_mcp.py:12-28`

**Step 1: Update imports and constants**

Replace this block in `ixnse_mcp.py` (lines 12–28):

```python
import json
import os
import tempfile
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE_URL = os.environ.get("IXNSE_API_URL", "http://localhost:8080").rstrip("/")
CHARACTER_LIMIT = 25_000
DEFAULT_TIMEOUT = 30.0
```

With:

```python
import json
import os
import tempfile
from contextvars import ContextVar
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BACKEND: str = os.environ.get("IXNSE_API_URL", "http://localhost:8080").rstrip("/")
_backend_url: ContextVar[str] = ContextVar("backend_url")
CHARACTER_LIMIT = 25_000
DEFAULT_TIMEOUT = 30.0
```

**Step 2: Update health endpoint** (lines 37–45)

Replace:
```python
@mcp.custom_route("/", methods=["GET"])
async def health(request: Any) -> Any:
    from starlette.responses import JSONResponse
    return JSONResponse({
        "service": "ixnse-mcp",
        "status": "ok",
        "mcp_endpoint": "/mcp",
        "backend": API_BASE_URL,
    })
```

With:
```python
@mcp.custom_route("/", methods=["GET"])
async def health(request: Any) -> Any:
    from starlette.responses import JSONResponse
    return JSONResponse({
        "service": "ixnse-mcp",
        "status": "ok",
        "mcp_endpoint": "/mcp",
        "default_backend": _DEFAULT_BACKEND,
        "backend_override": "append ?backend=<url> to /mcp URL to override per-session",
    })
```

**Step 3: Update `_api()` to read from ContextVar** (line 68)

Replace:
```python
    url = f"{API_BASE_URL}{path}"
```

With:
```python
    url = f"{_backend_url.get(_DEFAULT_BACKEND)}{path}"
```

**Step 4: Verify no other references to `API_BASE_URL` remain**

```bash
grep -n "API_BASE_URL" mcp/ixnse_mcp.py
```

Expected: no output.

**Step 5: Commit**

```bash
git add mcp/ixnse_mcp.py
git commit -m "refactor(mcp): replace API_BASE_URL global with ContextVar + _DEFAULT_BACKEND"
```

---

### Task 2: Add `BackendURLMiddleware` and wire into `main()`

**Files:**
- Modify: `mcp/ixnse_mcp.py` — server init section + `main()`

**Step 1: Add middleware class** after the `mcp = FastMCP(...)` line (after line 34):

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest


class BackendURLMiddleware(BaseHTTPMiddleware):
    """Extract ?backend= query param and set it in the ContextVar for the request lifetime."""

    async def dispatch(self, request: StarletteRequest, call_next: Any) -> Any:
        backend = request.query_params.get("backend")
        if backend:
            token = _backend_url.set(backend.rstrip("/"))
            try:
                return await call_next(request)
            finally:
                _backend_url.reset(token)
        return await call_next(request)
```

**Step 2: Update `main()` to wrap app and run via uvicorn**

Replace the current `main()`:

```python
def main() -> None:
    import argparse

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
        global API_BASE_URL
        API_BASE_URL = args.api_url.rstrip("/")

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport="streamable-http")
```

With:

```python
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
        global _DEFAULT_BACKEND
        _DEFAULT_BACKEND = args.api_url.rstrip("/")

    app = mcp.streamable_http_app()
    app.add_middleware(BackendURLMiddleware)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
```

**Step 3: Add `uvicorn` to dependencies in `pyproject.toml`**

```toml
dependencies = [
    "mcp[cli]>=1.0.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
    "uvicorn>=0.29.0",
]
```

**Step 4: Reinstall**

```bash
cd mcp && uv pip install -e .
```

**Step 5: Smoke test — start server, check health, check ?backend= override**

```bash
# Terminal 1
ixnse-mcp --api-url http://localhost:8080

# Terminal 2 — health shows default_backend
curl -s http://localhost:8889/ | python3 -m json.tool

# MCP initialize with ?backend= override
curl -s -X POST "http://localhost:8889/mcp?backend=http://other-ixnse:9090" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}'
```

Expected: `200 OK` for both. Health shows `"default_backend": "http://localhost:8080"`.

**Step 6: Commit**

```bash
git add mcp/ixnse_mcp.py mcp/pyproject.toml
git commit -m "feat(mcp): add BackendURLMiddleware — override backend via ?backend= query param"
```

---

### Task 3: Write tests

**Files:**
- Create: `mcp/tests/__init__.py`
- Create: `mcp/tests/test_backend_middleware.py`

**Step 1: Add pytest to dev deps in `pyproject.toml`**

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27.0",
]
```

Install:
```bash
cd mcp && uv pip install -e ".[dev]"
```

**Step 2: Write tests**

```python
# mcp/tests/test_backend_middleware.py
"""Tests for BackendURLMiddleware and ContextVar backend resolution."""
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import PlainTextResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ixnse_mcp as sut


def _make_test_app() -> Starlette:
    """Minimal Starlette app that echoes which backend ContextVar resolves to."""
    async def echo_backend(request):
        return PlainTextResponse(sut._backend_url.get(sut._DEFAULT_BACKEND))

    app = Starlette(routes=[Route("/", echo_backend)])
    app.add_middleware(sut.BackendURLMiddleware)
    return app


def test_no_backend_param_uses_default():
    client = TestClient(_make_test_app())
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == sut._DEFAULT_BACKEND


def test_backend_param_overrides():
    client = TestClient(_make_test_app())
    resp = client.get("/?backend=http://other:9090")
    assert resp.status_code == 200
    assert resp.text == "http://other:9090"


def test_backend_param_strips_trailing_slash():
    client = TestClient(_make_test_app())
    resp = client.get("/?backend=http://other:9090/")
    assert resp.status_code == 200
    assert resp.text == "http://other:9090"


def test_contextvar_resets_after_request():
    """ContextVar must not leak between requests."""
    client = TestClient(_make_test_app())
    client.get("/?backend=http://leaked:1234")
    resp = client.get("/")
    assert resp.text == sut._DEFAULT_BACKEND
```

**Step 3: Run tests**

```bash
cd mcp && uv run pytest tests/ -v
```

Expected: 4 tests pass.

**Step 4: Commit**

```bash
git add mcp/tests/ mcp/pyproject.toml
git commit -m "test(mcp): add BackendURLMiddleware unit tests"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md` — MCP Server section

**Step 1: Update the Claude Code and Claude Desktop config examples**

In the `## MCP Server` section, update the config snippets to show both the default form and the `?backend=` override form:

```markdown
### Add to Claude Code

```bash
# Default backend (http://localhost:8080)
claude mcp add --transport http ixnse http://localhost:8889/mcp

# Custom backend
claude mcp add --transport http ixnse "http://localhost:8889/mcp?backend=http://my-ixnse:8080"
```

Or manually in `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "ixnse": {
      "type": "http",
      "url": "http://localhost:8889/mcp?backend=http://my-ixnse:8080"
    }
  }
}
```
```

Apply the same pattern to the Claude Desktop section.

**Step 2: Add a note about the `?backend=` mechanism**

After the config blocks, add:

```markdown
> **Backend override:** Append `?backend=<url>` to the `/mcp` URL to point this MCP instance
> at a specific IxNSE backend. If omitted, the server uses the URL it was started with
> (`--api-url` or `IXNSE_API_URL`, defaulting to `http://localhost:8080`).
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update MCP config examples with ?backend= override"
```
