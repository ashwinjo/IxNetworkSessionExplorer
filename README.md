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

## Quickstart

### 1. Start all services

```bash
# First run — build images and start
./start.sh --build

# Subsequent starts
./start.sh
```

`start.sh` starts three services: **backend API** (port 8080), **frontend UI** (port 3000), and **MCP server** (port 8889).

> Ubuntu 20.04+: `start.sh` auto-installs Docker CE and the compose plugin if missing.
> Other systems: install [Docker](https://docs.docker.com/engine/install/) manually first.

### 2. Open the dashboard

Navigate to **http://localhost:3000**

### 3. Add an IxNetwork server

UI → **Manage Servers** → **Add Server**. Enter name, host/IP, username, password, REST port (default: 443). Click **Test Connection** to verify, then **Save**. Polling starts automatically every 60 s.

### 4. Connect Claude (optional)

The MCP server is already running at `http://localhost:8889/mcp`. Register it with Claude Code:

```bash
claude mcp add --transport http ixnse http://localhost:8889/mcp
```

Or for Claude Desktop — see [Configure: Claude Desktop](#configure-claude-desktop) below.

Then ask Claude: *"Show me all IxNetwork sessions and which ports are active."*

### Stop

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
| MCP Server | http://localhost:8889/mcp |

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

IxNSE ships an MCP server (`mcp/`) that exposes all session, server, chassis, and poller operations as tools for AI assistants (Claude Code, Claude Desktop, or any MCP-compatible client).

Transport: **streamable HTTP** — the MCP server runs as a standalone process; Claude connects to it over HTTP.

### Install

```bash
cd mcp
uv venv && source .venv/bin/activate
uv pip install -e .
```

### Start

**Via Docker (recommended) — started automatically by `./start.sh`:**

```bash
./start.sh          # starts backend + frontend + MCP
./start.sh --no-mcp # skip MCP if not needed
```

**MCP only (Docker) — when backend is already running elsewhere:**

```bash
# Build MCP image (first time only)
docker compose build mcp

# Start only the MCP container, pointed at a remote backend
IXNSE_API_URL=http://my-ixnse-host:8080 docker compose up -d mcp

# Or override inline without env var
docker run --rm -p 8889:8889 \
  -e IXNSE_API_URL=http://my-ixnse-host:8080 \
  ixnetworksessionexplorer-mcp
```

**Manually (outside Docker):**

```bash
# CLI arg (takes precedence over env var)
ixnse-mcp --api-url http://localhost:8080

# Or via environment variable
IXNSE_API_URL=http://localhost:8080 ixnse-mcp

# Custom bind host/port (default: 0.0.0.0:8889)
ixnse-mcp --api-url http://localhost:8080 --host 127.0.0.1 --port 9000

# Without installing (uv run)
cd mcp && uv run ixnse-mcp --api-url http://localhost:8080
```

The MCP endpoint is at `http://<host>:<port>/mcp`.
Health check: `http://<host>:<port>/` — returns JSON with current backend URL.

> The MCP server must be running before Claude connects. Start it before launching Claude Desktop or opening a Claude Code session.

---

### Configure: Claude Code

#### Option 1 — CLI (recommended)

```bash
# Per-workspace (default scope — stored in local .claude/ dir, not committed)
claude mcp add --transport http ixnse http://localhost:8889/mcp

# User-wide — available in all your workspaces
claude mcp add --transport http --scope user ixnse http://localhost:8889/mcp

# Project-wide — committed to repo as .mcp.json, shared with team
claude mcp add --transport http --scope project ixnse http://localhost:8889/mcp

# Point at a remote IxNSE backend (backend override)
claude mcp add --transport http ixnse "http://localhost:8889/mcp?backend=http://ixnse.lab.example.com:8080"
```

Verify the server registered:

```bash
claude mcp list
```

#### Option 2 — Manual JSON

User-wide (`~/.claude/settings.json`) or project-level (`.claude/settings.json` in repo root):

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

With a remote backend override:

```json
{
  "mcpServers": {
    "ixnse": {
      "type": "http",
      "url": "http://localhost:8889/mcp?backend=http://ixnse.lab.example.com:8080"
    }
  }
}
```

---

### Configure: Claude Desktop

Edit the config file for your OS:

| OS | Config file |
|----|-------------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

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

With a remote backend override:

```json
{
  "mcpServers": {
    "ixnse": {
      "type": "http",
      "url": "http://localhost:8889/mcp?backend=http://ixnse.lab.example.com:8080"
    }
  }
}
```

**Restart Claude Desktop after editing the config.**

---

### Backend Override

By default the MCP server targets the IxNSE backend it was started with (`--api-url` / `IXNSE_API_URL`, default `http://localhost:8080`).

Append `?backend=<url>` to the `/mcp` URL to redirect a specific Claude session to a different backend — useful when one MCP process serves multiple users or environments:

```
http://localhost:8889/mcp?backend=http://ixnse-prod.lab.example.com:8080
```

The override is per-connection and does not affect other connected clients.

---

## Local Dev (no Docker)

Each component runs in its own terminal.

**Terminal 1 — Backend:**
```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload
```

**Terminal 2 — Frontend:**
```bash
cd frontend && python3 -m http.server 3000
```

**Terminal 3 — MCP server:**
```bash
cd mcp
uv venv && source .venv/bin/activate
uv pip install -e .
ixnse-mcp --api-url http://localhost:8080
```
