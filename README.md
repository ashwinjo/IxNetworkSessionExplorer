# IxNetwork Session Explorer (IxNSE)

Unified dashboard for lab admins to track IxNetwork sessions across multiple chassis — showing which sessions are actively using resources (control plane + data plane).

No config file required. All servers are added and managed through the UI. Settings persist in SQLite across restarts.

---

## Quickstart

### Prerequisites

- Docker + `docker compose`
- Access to one or more IxNetwork servers

### 1. Clone

```bash
git clone https://github.com/yourusername/IxNetworkSessionExplorer.git
cd IxNetworkSessionExplorer
```

### 2. Start

```bash
./start.sh
```

First run builds the backend image (~2 min). Subsequent starts are instant.

To force a rebuild: `./start.sh --build`

### 3. Add servers

Open the UI → **Manage Servers** → **Add Server**.

Fill in name, host/IP, username, password, and optional REST port (default: auto-detect 443/11009).

The poller starts automatically every 60 seconds. Change the interval anytime via the **Poll: 60s** button in the toolbar.

### 4. Services

| Service | URL |
|---------|-----|
| Frontend UI | http://0.0.0.0:3000 |
| Backend API | http://0.0.0.0:8080 |
| API Docs | http://0.0.0.0:8080/docs |
| Health Check | http://0.0.0.0:8080/health/ |
| Prometheus Metrics | http://0.0.0.0:8080/metrics |

### Stop

```bash
docker compose down         # stop containers
docker compose down -v      # stop + delete database
```

---

## Environment Variables

All optional. Set in your shell or in `docker-compose.yml`.

| Variable | Default | Description |
|----------|---------|-------------|
| `IXSE_DB` | `ixse.db` | Path to the SQLite database file |
| `IXSE_POLL_INTERVAL` | `60` | Initial poll interval in seconds (overridden by any value previously saved via the UI) |

---

## API Endpoints

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions` | All sessions across all servers |
| `GET` | `/sessions/{server}/{id}` | Single session detail |
| `PATCH` | `/sessions/{server}/{id}/tags` | Add / remove tags |
| `DELETE` | `/sessions/{server}/{id}?confirm=true` | Kill a session |
| `POST` | `/sessions/{server}/{id}/collect-logs` | Download diagnostic logs as zip |

### Servers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/servers` | List all configured servers (password masked) |
| `POST` | `/servers` | Add a new server |
| `PUT` | `/servers/{name}` | Update an existing server |
| `DELETE` | `/servers/{name}` | Remove a server |
| `POST` | `/servers/{name}/test` | Test RestPy connectivity |
| `POST` | `/servers/{name}/probe-web` | Run IxNetwork Web HTTPS auth probe |
| `PATCH` | `/servers/{name}/tags` | Add / remove server tags |
| `POST` | `/servers/bulk` | Upsert multiple servers |
| `DELETE` | `/servers/bulk` | Delete multiple servers |
| `PATCH` | `/servers/bulk/password` | Update password for multiple servers |

### Poller

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/poll/trigger` | Force an immediate poll cycle |
| `GET` | `/poll/status` | Last poll time, next scheduled, is_polling flag |
| `GET` | `/poll/config` | Current poll interval |
| `PATCH` | `/poll/config` | Update poll interval (persisted to DB) |

### Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Fleet health check |
| `GET` | `/metrics` | Prometheus metrics |

---

## Local Dev (no Docker)

```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload

# Serve frontend separately
cd ../frontend && python3 -m http.server 3000
```

No config file needed. Start the server, then add IxNetwork servers via the UI or `POST /servers`.

---

## References

- [RestPy](https://github.com/OpenIxia/ixnetwork_restpy)
- [FastAPI](https://fastapi.tiangolo.com/)
