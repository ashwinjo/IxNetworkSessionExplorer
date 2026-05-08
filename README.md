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
- **CLI** — `ixse` commands for quick inspection

---

## Architecture

```
IxNetwork Servers  ──►  RestPy (CP)  ─┐
                                       ├──►  FastAPI  ──►  Web UI  /
IxOS Chassis       ──►  REST  (DP)  ──┘      + CLI         API     /sessions
                                              + Prometheus  Metrics /metrics
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

## Quick Start

### Option A — Docker (recommended)

**Prerequisites:** Docker + Docker Compose

**1. Copy and edit the config file**

```bash
cp backend/ixse_config.yaml.example backend/ixse_config.yaml
```

Edit `backend/ixse_config.yaml` — add your IxNetwork server(s):

```yaml
poller:
  interval_seconds: 60

ixnet_servers:
  - name: ixnet-server-01
    host: 10.1.1.100          # IP or hostname of your IxNetwork server
    username: admin
    password: ${IXNET_PASSWORD}   # set via env var below
    # rest_port: 443            # uncomment for HTTPS-only servers
```

**2. Export credentials**

```bash
export IXNET_PASSWORD="your-ixnetwork-password"
# If you have IxOS chassis configured:
export IXOS_PASSWORD="your-ixos-password"
```

**3. Start the stack**

```bash
docker compose up -d
```

**4. Open the dashboard**

- Web UI: [http://localhost:8080](http://localhost:8080)
- REST API docs: [http://localhost:8080/docs](http://localhost:8080/docs)
- Prometheus metrics: [http://localhost:8080/metrics](http://localhost:8080/metrics)

**5. Stop**

```bash
docker compose down
```

---

### Option B — Local Python

**Prerequisites:** Python 3.11+

**1. Create and activate a virtual environment**

```bash
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
```

**2. Install the package**

```bash
cd backend
pip install -e ".[dev]"           # dev extras include pytest, black, ruff
```

**3. Copy and edit config**

```bash
cp ixse_config.yaml.example ixse_config.yaml
# Edit ixse_config.yaml — add your IxNetwork server(s)
```

**4. Export credentials and start the server**

```bash
export IXNET_PASSWORD="your-ixnetwork-password"
uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload
```

**5. Open the dashboard**

- Web UI + API docs: [http://localhost:8080](http://localhost:8080)

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

## Prometheus / Grafana

The `/metrics` endpoint exports standard Prometheus gauges:

```
ixse_session_utilized{session="bgp-01", server="ixnet-01"} 1
ixse_session_cp_active{session="bgp-01", server="ixnet-01"} 1
ixse_session_dp_active{session="bgp-01", server="ixnet-01"} 1
ixse_sessions_total{server="ixnet-01"} 3
ixse_chassis_reachable{chassis="lab-01"} 1
```

Add IxNSE as a Prometheus scrape target:

```yaml
scrape_configs:
  - job_name: ixnse
    static_configs:
      - targets: ['localhost:8080']
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
- [Typer CLI](https://typer.tiangolo.com/)
