# Design: MCP Backend URL Override via Query Parameter

**Date:** 2026-05-22
**Status:** Approved

## Problem

The IxNSE MCP server runs as a persistent streamable-HTTP service on port 8889.
For `type: "http"` MCP configs, Claude only sends `{type, url}` — no `env` or `args`.
There is no built-in mechanism to inject the backend API URL from the config.

## Solution

Encode the IxNSE backend URL as a `?backend=` query parameter on the MCP endpoint URL.
MCP streamable-HTTP sends every request (initialize + all tool calls) to the same full URL,
so the query param is present on every request in the session.

### Claude Config Example

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

If `?backend=` is omitted, the server falls back to the default (`http://localhost:8080`).

## Architecture

### ContextVar for per-request backend URL

Replace the module-level `API_BASE_URL` string (used as a global mutable) with a
`contextvars.ContextVar`. This provides correct async isolation — each request's task
gets its own value without thread-safety concerns.

```
_backend_url: ContextVar[str] = ContextVar("backend_url", default="http://localhost:8080")
```

### Starlette Middleware

A `BaseHTTPMiddleware` wraps the FastMCP Starlette app. On every request:
1. Extract `?backend=` from query params
2. If present: set `_backend_url` ContextVar for the duration of that request
3. Call next handler
4. ContextVar resets automatically (token-based reset)

```
POST /mcp?backend=http://prod:8080
  → middleware sets _backend_url = "http://prod:8080"
  → tool executes, _api() reads _backend_url.get()
  → hits http://prod:8080
  → response returns, ContextVar resets

POST /mcp  (no param)
  → middleware: no ?backend → no ContextVar override
  → tools hit default http://localhost:8080
```

### _api() change

```python
# Before
url = f"{API_BASE_URL}{path}"

# After
url = f"{_backend_url.get()}{path}"
```

### Health endpoint update

`GET /` returns `default_backend` (module-level default) and `effective_backend`
(ContextVar value — always the default at health-check time since no session context).

## Startup Behaviour (unchanged)

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8889` | MCP server listen port |
| `--host` | `0.0.0.0` | Bind address |
| `--api-url` | `http://localhost:8080` | Default backend (env: `IXNSE_API_URL`) |

`--api-url` / `IXNSE_API_URL` sets the **default** backend used when no `?backend=` param
is present. The query param always overrides it per-request.

## Files Changed

- `mcp/ixnse_mcp.py` — ContextVar, middleware, `_api()`, health endpoint
- `mcp/README.md` or root `README.md` — update config examples with `?backend=` usage

## Non-Goals

- No authentication on the `?backend=` param (internal lab tool, trusted network)
- No validation that the backend URL is reachable before accepting the session
- No per-session persistence of the backend URL (query param on every request is sufficient)
