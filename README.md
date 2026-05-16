# IxNetwork Session Explorer (IxNSE)

Unified dashboard for lab admins to track IxNetwork sessions across multiple chassis — showing which sessions are actively using resources (control plane + data plane).

No config file required. All servers are added and managed through the UI. Settings persist in SQLite across restarts.

---

## Quickstart

### Prerequisites

- `git`
- `sudo` privileges (Ubuntu only — needed for automatic Docker install)
- Access to one or more IxNetwork servers

> **On Ubuntu 20.04+:** `start.sh` automatically installs Docker CE, the compose plugin, and `curl` if they are missing. No manual Docker setup needed.
>
> **On other systems:** Install [Docker](https://docs.docker.com/engine/install/) and the compose plugin manually before running `start.sh`.

> **Container base image:** `python:3.11-slim` (Debian-based, ~130 MB). Runs on any Linux host regardless of host distro.

### 1. Clone

```bash
sudo apt install -y git          # Ubuntu only — skip if git already installed
git clone https://github.com/yourusername/IxNetworkSessionExplorer.git
cd IxNetworkSessionExplorer
```

### 2. Start

```bash
./start.sh --build   # first run: builds the backend image (~2 min)
./start.sh           # subsequent runs: instant start, no rebuild
```

`start.sh` sequentially:
1. Installs missing dependencies (Ubuntu only: `curl`, Docker CE, compose plugin)
2. Starts the Docker daemon if not running
3. Builds images (only with `--build`)
4. Starts the backend and waits for `/health/` to pass
5. Starts the frontend

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
