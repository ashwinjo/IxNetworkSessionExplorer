# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IxNetwork Session Explorer (IxNSE) — unified dashboard for lab admins to track IxNetwork sessions across multiple chassis. Shows which sessions actively use resources (control plane + data plane). No config file required — servers are managed via UI/API and persisted in SQLite.

## Commands

### Local Dev (no Docker)

```bash
cd backend
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run backend API
uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload

# Serve frontend
cd ../frontend && python3 -m http.server 3000
```

### Tests

```bash
cd backend
pytest                                    # all tests + coverage
pytest tests/unit/test_client.py          # single file
pytest tests/unit/ -k "test_kill"         # single test by name
pytest --no-cov                           # skip coverage
```

### Linting / Formatting

```bash
cd backend
ruff check ixse/                          # lint
ruff check ixse/ --fix                    # auto-fix
black ixse/                               # format
mypy ixse/                                # type check
```

### Docker

```bash
# Normal (Docker has internet):
make build && make up

# Offline Docker build (no internet in container):
make vendor    # downloads wheels to backend/vendor/ — re-run when requirements.txt changes
make build
make up

make down      # stop
make logs      # tail logs
docker compose down -v   # stop + delete DB volume
```

### CLI (after install)

```bash
ixse --help
ixse sessions list
ixse chassis list
ixse health check
IXSE_API_URL=http://myserver:8080 ixse sessions list
```

## Architecture

### Stack

- **Backend:** FastAPI + uvicorn, Python 3.11+, Pydantic v2, SQLite (via stdlib), `ixnetwork_restpy`
- **Frontend:** Vanilla JS/HTML/CSS — no framework. Served as static files by FastAPI in dev, nginx in Docker.
- **Package manager:** `uv` (preferred over pip for speed). `pyproject.toml` is the source of truth.

### Backend Package Layout (`backend/ixse/`)

```
ixse/
├── api/
│   ├── main.py          # App factory, lifespan, background poller, poll/* endpoints
│   ├── state.py         # FleetState — SQLite + in-memory cache (single source of truth)
│   ├── metrics.py       # Prometheus metrics
│   └── routers/
│       ├── sessions.py  # GET/PATCH/DELETE /sessions/*
│       ├── servers.py   # CRUD /servers/* including bulk ops
│       ├── chassis.py   # GET /sessions/ports/* utilized endpoint
│       └── health.py    # GET /health/
├── client.py            # RestPyClient — wraps ixnetwork_restpy TestPlatform
├── plane.py             # CP/DP detection logic (detect_cp_per_vport, detect_cp, detect_dp)
├── models.py            # All Pydantic models (Session, SessionPort, ServerEntry, etc.)
├── ixn_web.py           # IxNetwork Web HTTPS auth probe (check_ixnetwork_web)
├── ixos.py              # IxOS chassis client (for DP/frame-count detection)
├── config.py            # IxNetServerConfig, optional ixse_config.yaml seed loading
├── health.py            # Fleet health check implementation
└── cli/
    ├── main.py          # Typer root app (ixse server start|stop)
    ├── sessions.py      # ixse sessions subcommands
    ├── chassis.py       # ixse chassis subcommands
    ├── health.py        # ixse health subcommands
    ├── _api.py          # HTTP client helpers for CLI → API calls
    └── state.py         # CLI global state (api_url)
```

### Data Flow — Poll Cycle

1. `poll_fleet()` background task (asyncio) fires every `poll_interval_seconds`
2. For each server in DB: `poll_server()` runs sync in a thread executor
3. `RestPyClient.connect()` → `TestPlatform.Authenticate()` (no session created)
4. `get_raw_sessions()` — enumerates EXISTING sessions only, never creates one
5. Per session: fetch Vports → `_parse_vports()` → `SessionPort` list
6. Per vport: `detect_cp_per_vport()` checks Topology → DeviceGroup status
7. `fetch_lldp_map()` reads IxNetwork Locations API for per-port LLDP neighbors
8. `fetch_session_errors()` reads AppErrors (kError level)
9. `state.upsert_session()` — writes to SQLite + in-memory cache; preserves user tags

### State Management (`FleetState`)

- Single SQLite connection with `threading.Lock` for all writes
- In-memory dict cache `{(server_name, session_id): Session}` for lock-free reads
- Schema migrations are additive `ALTER TABLE` statements (safe to re-run)
- Session tags set via PATCH are preserved across poll cycles — poller never clobbers non-empty tags

### Key Design Invariants

- `Session.cp_active`, `dp_active`, `utilized` are **computed by `model_validator`** from ports — never set directly
- `SessionPort.utilized = cp_active OR dp_active` — same pattern
- `RestPyClient` is **read/inspect/kill only** — never creates sessions
- CP detection uses Topology → DeviceGroup `Status` field; DP detection uses IxOS port frame counters (currently `dp_active=False` for all ports — Phase 2)
- `ixnetwork_restpy` is optional at import time — tests run without it

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `IXSE_DB` | `ixse.db` | SQLite DB path |
| `IXSE_POLL_INTERVAL` | `60` | Initial poll interval (seconds); DB value wins if set |
| `IXSE_API_URL` | `http://localhost:8080` | CLI → API base URL |

## Frontend Design System

Full spec in `Design.md`. Key constraints:

- **Dark-only** — no light mode, no media query branching
- All CSS values derived from CSS custom properties on `:root` — never hardcode hex values
- Monospace fonts everywhere (`--font-display: Syne Mono`, `--font-mono: JetBrains Mono`)
- Status semantics: `--cyan` = interactive, `--green` = active/healthy, `--amber` = degraded/tags, `--crimson` = error/danger
- Multi-port sessions: first port row uses `rowspan="N"` for SESSION/CP/DP/UTILIZED/ACTIONS; sub-rows carry only CHASSIS and PORT cells

## Testing Notes

- `tests/unit/` — pure unit tests; all RestPy calls mocked via `unittest.mock`. No IxNetwork required.
- `tests/integration/test_api.py` — FastAPI `TestClient` with in-memory SQLite (`FleetState(":memory:")`)
- `asyncio_mode = "auto"` in pytest config — async tests work without `@pytest.mark.asyncio`
- Line length: 100 chars (`black` + `ruff`)
