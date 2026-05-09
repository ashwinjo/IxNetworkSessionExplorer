# IxNetwork Session Explorer (IxNSE)

Unified session manager for lab administrators to track IxNetwork sessions across multiple chassis.

**Core question it answers:** Which sessions are actively utilizing resources (control plane + data plane)?

---

## What It Does

Lab admins today must log into each IxNetwork server individually to check whether sessions are idle or active. IxNSE solves this with:

- **Session discovery** — polls all configured IxNetwork servers every 60 s (configurable)
- **Utilization detection** — fuses Control Plane (RestPy protocol state) + Data Plane (IxOS TX/RX frames) signals
- **REST API** — FastAPI server with OpenAPI docs at `/docs`
- **Web UI** — dark-themed dashboard served at `/`
- **Prometheus metrics** — exportable gauges at `/metrics`

> **Not yet implemented:** CLI (`ixse` commands) — modules exist as stubs but commands are not functional.

---

## Architecture

```
IxNetwork Servers  ──►  RestPy (CP)  ─┐
                                       ├──►  FastAPI  ──►  Web UI  :3000
IxOS Chassis       ──►  REST  (DP)  ──┘              ──►  API     :8080/sessions
                                                      ──►  Metrics :8080/metrics
```

Utilization = `CP_ACTIVE AND DP_ACTIVE`

---

## Project Structure

```
backend/
├── ixse/
│   ├── config.py          # YAML config loader + Pydantic models
│   ├── client.py          # RestPy abstraction (Control Plane)
│   ├── ixos.py            # IxOS REST abstraction (Data Plane)
│   ├── ixn_web.py         # IxNetwork Web API (alternative session source)
│   ├── models.py          # Session, Port, PlaneStatus data models
│   ├── plane.py           # CP + DP detection logic
│   ├── health.py          # Reachability checks
│   └── api/
│       ├── main.py        # FastAPI app + background poller
│       ├── state.py       # SQLite persistence layer
│       ├── metrics.py     # Prometheus gauge definitions
│       └── routers/
│           ├── sessions.py
│           ├── servers.py
│           └── health.py
├── Dockerfile
├── requirements.txt
└── ixse_config.yaml.example

frontend/
├── index.html             # Dashboard SPA
├── style.css
└── app.js

docker-compose.yml         # One-command deployment
```

---

## Quickstart (Ubuntu)

These steps assume a fresh Ubuntu 22.04+ box with `git`, `docker`, and `docker compose` available.

### 0. Prerequisites

```bash
# Install Docker (skip if already installed)
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow running docker without sudo (log out and back in after this)
sudo usermod -aG docker $USER
newgrp docker
```

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/IxNetworkSessionExplorer.git
cd IxNetworkSessionExplorer
```

### 2. Create your config file

```bash
cp backend/ixse_config.yaml.example backend/ixse_config.yaml
```

Open `backend/ixse_config.yaml` in your editor and set your IxNetwork server details:

```yaml
poller:
  interval_seconds: 60

ixnet_servers:
  - name: ixnet-server-01
    host: 10.1.1.100          # IP or hostname of your IxNetwork server
    username: admin
    password: ${IXNET_PASSWORD}   # supplied via env var below
    # rest_port: 443            # uncomment for HTTPS-only servers
```

### 3. Export credentials

```bash
export IXNET_PASSWORD="your-ixnetwork-password"
# Only needed if you have IxOS chassis configured for data-plane detection:
# export IXOS_PASSWORD="your-ixos-password"
```

### 4. Start the stack

```bash
docker compose up -d
```

On first run Docker will build the backend image (~2 min). Subsequent starts are instant.

### 5. Open the dashboard

| What | URL |
|------|-----|
| Web UI (dashboard) | [http://localhost:3000](http://localhost:3000) |
| REST API | [http://localhost:8080](http://localhost:8080) |
| OpenAPI docs | [http://localhost:8080/docs](http://localhost:8080/docs) |
| Prometheus metrics | [http://localhost:8080/metrics](http://localhost:8080/metrics) |

### 6. Verify it's running

```bash
# Container health
docker compose ps

# Confirm API responds
curl -s http://localhost:8080/health/ | python3 -m json.tool

# Force an immediate poll instead of waiting 60 s
curl -s -X POST http://localhost:8080/poll/trigger | python3 -m json.tool
```

### 7. Stop

```bash
docker compose down
# To also delete the persisted SQLite database:
docker compose down -v
```

---

## Local Python (no Docker)

**Prerequisites:** Python 3.11+

```bash
# 1. Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 2. Install the package
cd backend
pip install -e ".[dev]"

# 3. Copy and edit config
cp ixse_config.yaml.example ixse_config.yaml
# Edit ixse_config.yaml — add your IxNetwork server(s)

# 4. Export credentials and start the server
export IXNET_PASSWORD="your-ixnetwork-password"
uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload
```

Open the API at [http://localhost:8080](http://localhost:8080).

> When running locally without Docker the frontend files in `frontend/` need a static file server pointed at them (e.g. `python3 -m http.server 3000` from the `frontend/` directory).

---

## Configuration Reference

`ixse_config.yaml` — see `backend/ixse_config.yaml.example` for a full annotated example.

| Key | Default | Description |
|-----|---------|-------------|
| `poller.interval_seconds` | `60` | How often to poll servers |
| `ixnet_servers[].name` | — | Display name for this server |
| `ixnet_servers[].host` | — | IP / hostname |
| `ixnet_servers[].username` | — | Login username |
| `ixnet_servers[].password` | — | Password (use `${ENV_VAR}` for secrets) |
| `ixnet_servers[].rest_port` | auto | `443` for HTTPS-only, `11009` for classic HTTP |

Credentials can use shell env-var interpolation: `password: ${MY_SECRET}`.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions` | All sessions across all servers |
| `GET` | `/sessions/{server}/{id}` | Single session detail |
| `PATCH` | `/sessions/{server}/{id}/tags` | Add / remove tags |
| `DELETE` | `/sessions/{server}/{id}?confirm=true` | Kill a session |
| `POST` | `/poll/trigger` | Force an immediate poll |
| `GET` | `/poll/status` | Last poll timestamp + result |
| `GET` | `/health` | Fleet heartbeat |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | Interactive OpenAPI docs |

---

## Running Tests

```bash
cd backend
source venv/bin/activate

# Unit tests (no IxNetwork access required)
pytest tests/unit/ -v

# All tests with coverage
pytest --cov=ixse --cov-report=term-missing

# Lint + format check
ruff check ixse/ tests/
black --check ixse/ tests/
```

---
## Development Workflow

```bash
# Format
black ixse/ tests/

# Lint (auto-fix)
ruff check --fix ixse/ tests/

# Type check
mypy ixse/

# Auto-reload server
uvicorn ixse.api.main:app --reload
```

Commit style: [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).

---

## References

- [Project Vision](project_vision.md)
- [Architecture Docs](docs/vision/)
- [RestPy](https://github.com/OpenIxia/ixnetwork_restpy)
- [FastAPI](https://fastapi.tiangolo.com/)
