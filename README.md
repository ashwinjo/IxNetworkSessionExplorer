# IxNetwork Session Explorer (IxNSE)

## App Preview

**Day mode**
![Day mode — main dashboard](docs/screenshots/day-mode.png)

**Night mode**
![Night mode — main dashboard](docs/screenshots/night-mode.png)

**Manage Servers**
![Manage Servers modal](docs/screenshots/manage-servers.png)

---


Dashboard for lab admins to track IxNetwork sessions across multiple chassis. Shows which sessions are actively using resources (control plane + data plane). No config file — servers managed via UI, settings persisted in SQLite.

---

## Run

**First run (builds image):**
```bash
./start.sh --build
```

**Subsequent starts:**
```bash
./start.sh
```

> Ubuntu 20.04+: `start.sh` auto-installs Docker CE and the compose plugin if missing.
> Other systems: install [Docker](https://docs.docker.com/engine/install/) manually first.

**Stop:**
```bash
docker compose down        # stop
docker compose down -v     # stop + delete database
```

---

## Services

| Service | URL |
|---------|-----|
| UI | http://localhost:3000 |
| API | http://localhost:8080 |
| API Docs (Swagger) | http://localhost:8080/docs |
| Health | http://localhost:8080/health/ |
| Metrics (Prometheus) | http://localhost:8080/metrics |

---

## Adding Servers

UI → **Manage Servers** → **Add Server**.
Enter name, host/IP, username, password, REST port (default: 443).
Use **Test Connection** to verify credentials before saving.
Polling starts automatically every 60 s. Adjust via the **Poll** button in the toolbar.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IXSE_DB` | `ixse.db` | SQLite database path |
| `IXSE_POLL_INTERVAL` | `60` | Poll interval in seconds (UI value takes precedence) |

---

## API

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions` | All sessions across all servers |
| `GET` | `/sessions/{server}/{id}` | Single session detail |
| `PATCH` | `/sessions/{server}/{id}/tags` | Add / remove tags |
| `DELETE` | `/sessions/{server}/{id}?confirm=true` | Kill session |
| `POST` | `/sessions/{server}/{id}/collect-logs` | Download diagnostic logs |

### Servers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/servers` | List servers (password masked) |
| `POST` | `/servers` | Add server |
| `PUT` | `/servers/{name}` | Update server |
| `DELETE` | `/servers/{name}` | Remove server |
| `POST` | `/servers/probe` | Test credentials without saving |
| `POST` | `/servers/{name}/test` | Test saved server connectivity |
| `PATCH` | `/servers/{name}/tags` | Add / remove server tags |
| `POST` | `/servers/bulk` | Upsert multiple servers |
| `DELETE` | `/servers/bulk` | Delete multiple servers |
| `PATCH` | `/servers/bulk/password` | Update password for multiple servers |

### Poller

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/poll/trigger` | Force immediate poll |
| `GET` | `/poll/status` | Last/next poll time, is_polling flag |
| `PATCH` | `/poll/config` | Update poll interval |

---

## MCP Server

IxNSE ships an MCP server (`mcp/`) that exposes all session, server, chassis, and poller operations as tools for AI assistants.

### Install

```bash
cd mcp
uv pip install -e .
```

### Start

```bash
# CLI arg (takes precedence over env var)
ixnse-mcp --api-url http://localhost:8080

# Or via environment variable
IXNSE_API_URL=http://localhost:8080 ixnse-mcp

# Custom host/port (default: 0.0.0.0:8889)
ixnse-mcp --api-url http://localhost:8080 --host 127.0.0.1 --port 9000
```

The server listens at `http://<host>:<port>/mcp` (streamable HTTP transport).

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

### Add to Claude Desktop

In `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

Restart Claude Desktop after editing.

> **Backend override:** Append `?backend=<url>` to the `/mcp` URL to point this MCP instance
> at a specific IxNSE backend. If omitted, the server uses the URL it was started with
> (`--api-url` or `IXNSE_API_URL`, defaulting to `http://localhost:8080`).

> **Note:** The MCP server must be running before Claude connects to it. The default backend URL is set at startup via `--api-url` or `IXNSE_API_URL`. Per-connection overrides use `?backend=<url>` in the MCP URL.

---

## Local Dev (no Docker)

```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload

# In a separate terminal
cd frontend && python3 -m http.server 3000
```
