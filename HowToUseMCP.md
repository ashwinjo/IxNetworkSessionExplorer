# IxNSE MCP Server — Client Configuration Guide

The IxNSE MCP server runs on `http://localhost:8889/mcp` (Streamable HTTP transport).
Start it with: `cd mcp && uv run python ixnse_mcp.py`
Or via Docker Compose — the `mcp` service binds port 8889.

**Docker:** MCP container reaches the backend at `http://host.docker.internal:8080` (host machine).
`extra_hosts: host.docker.internal:host-gateway` is set in `docker-compose.yml` for Linux compat.
Override per-deployment: set `IXNSE_API_URL` env var before `docker compose up`.

Override backend URL per-session: `http://localhost:8889/mcp?backend=http://other-host:8080`

---

## Claude Desktop

Claude Desktop supports stdio MCP only. Use `mcp-remote` as a local proxy.

**File:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
**File:** `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "ixnse": {
      "command": "npx",
      "args": [
        "mcp-remote@0.1.38",
        "http://localhost:8889/mcp"
      ]
    }
  }
}
```

Restart Claude Desktop after editing. `npx` must be on PATH (install Node.js if missing).

---

## Claude Code (CLI)

Supports native HTTP MCP. Add to global user settings:

**File:** `~/.claude/settings.json`

```json
{
  "mcpServers": {
    "ixnse": {
      "type": "http",
      "url": "http://localhost:8889/mcp"
    }
  }
}
```

Or project-scoped (checked into repo):

**File:** `.mcp.json` at project root

```json
{
  "mcpServers": {
    "ixnse": {
      "type": "http",
      "url": "http://localhost:8889/mcp"
    }
  }
}
```

---

## Cursor

**Global:** `~/.cursor/mcp.json`
**Project:** `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "ixnse": {
      "command": "npx",
      "args": [
        "mcp-remote@0.1.38",
        "http://localhost:8889/mcp"
      ]
    }
  }
}
```

Cursor 0.47+ supports HTTP directly (no mcp-remote needed):

```json
{
  "mcpServers": {
    "ixnse": {
      "url": "http://localhost:8889/mcp",
      "transport": "http-streaming"
    }
  }
}
```

Enable in Cursor Settings > Features > MCP.

---

## Windsurf (Codeium)

**File:** `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "ixnse": {
      "command": "npx",
      "args": [
        "mcp-remote@0.1.38",
        "http://localhost:8889/mcp"
      ]
    }
  }
}
```

Reload Windsurf after editing. MCP tools appear in the Cascade panel.

---

## Cline (VS Code Extension)

Open VS Code Settings (`Cmd+,`) > search `cline mcp` > Edit in `settings.json`:

```json
{
  "cline.mcpServers": {
    "ixnse": {
      "command": "npx",
      "args": [
        "mcp-remote@0.1.38",
        "http://localhost:8889/mcp"
      ],
      "disabled": false
    }
  }
}
```

Or use the Cline sidebar > MCP Servers tab > Add Server.

---

## Continue (VS Code / JetBrains)

**File:** `~/.continue/config.json`

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "npx",
          "args": [
            "mcp-remote@0.1.38",
            "http://localhost:8889/mcp"
          ]
        }
      }
    ]
  }
}
```

---

## Zed Editor

**File:** `~/.config/zed/settings.json`

```json
{
  "context_servers": {
    "ixnse": {
      "command": {
        "path": "npx",
        "args": [
          "mcp-remote@0.1.38",
          "http://localhost:8889/mcp"
        ]
      }
    }
  }
}
```

---

## Generic MCP Client (stdio via mcp-remote)

Any MCP client that supports stdio servers can use `mcp-remote` as a bridge:

```bash
# Direct invocation
npx mcp-remote@0.1.38 http://localhost:8889/mcp

# With backend override
npx mcp-remote@0.1.38 "http://localhost:8889/mcp?backend=http://prod-host:8080"
```

---

## Verifying the Server is Up

```bash
# Health check (no special headers needed)
curl http://localhost:8889/

# Full MCP handshake test
curl -s -X POST http://localhost:8889/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

Expected health response: `{"service":"ixnse-mcp","status":"ok",...}`

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Not Acceptable: Client must accept text/event-stream` | Client sent GET without SSE header | Use MCP client, not bare curl/browser |
| `Bad Request: Missing session ID` | No MCP handshake performed | Client must POST `initialize` first |
| `Not valid MCP server configuration` (Claude Desktop) | Used `"type": "http"` in Desktop config | Use `mcp-remote` wrapper instead |
| `Cannot connect to IxNSE` | Backend not running | Start backend on port 8080 first |
| `npx: command not found` | Node.js not installed | Install Node.js 18+ |
