# IxNetwork Session Explorer - Backend

Backend service for unified IxNetwork session discovery and management across multiple servers.

## Quick Start

### Installation

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install with production dependencies
pip install -e .

# Or, for development (includes test/lint tools):
pip install -e ".[dev]"
```

### Running the Server

```bash
# Start the API server (requires ixse_config.yaml in parent directory)
uvicorn ixse.api.main:app --host 0.0.0.0 --port 8080 --reload
```

The server will:
- Expose REST API at `http://localhost:8080`
- Display interactive docs at `http://localhost:8080/docs`
- Run background poller every 60s (configurable in YAML)
- Store session data in SQLite database

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ixse

# Run only unit tests (fast)
pytest tests/unit/

# Run specific test file
pytest tests/test_api.py -v
```

## Project Structure

```
ixse/
├── __init__.py           # Package entry point
├── config.py             # YAML config loader + models
├── client.py             # RestPy abstraction (IxNetwork API)
├── ixos.py              # IxOS REST abstraction (port stats)
├── models.py            # Pydantic data models
├── plane.py             # CP/DP detection logic
├── api/
│   ├── __init__.py
│   ├── main.py          # FastAPI app + background poller
│   ├── state.py         # SQLite persistence layer
│   └── routers/
│       ├── __init__.py
│       └── sessions.py  # Session CRUD endpoints
└── tests/
    └── test_api.py      # Integration tests
```

## Dependencies

- **fastapi ~0.100**: REST framework
- **uvicorn ~0.23**: ASGI server
- **ixnetwork-restpy >=1.0**: IxNetwork API client
- **pydantic >=2.0**: Data validation
- **pyyaml >=6.0**: Config parsing
- **requests >=2.31**: HTTP client (IxOS REST)
- **prometheus-client >=0.17**: Metrics export

See `pyproject.toml` for full dependency list.

## Configuration

Create `ixse_config.yaml` (see `ixse_config.yaml.example`):

```yaml
poller:
  interval_seconds: 60

ixnet_servers:
  - name: ixnet-server-01
    host: 10.1.1.100
    username: admin
    password: ${IXNET_PASSWORD}
```

Set environment variables before running:
```bash
export IXNET_PASSWORD="your-password"
```

## API Endpoints

See OpenAPI docs (`/docs`) for full specification with request/response schemas.

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions/` | List all sessions grouped by server |
| `GET` | `/sessions/ports/{chassis}/{card}/{port}/utilized` | Check if a port has CP or DP active |
| `GET` | `/sessions/{server}/{session_id}` | Session detail (ports, plane status, tags) |
| `PATCH` | `/sessions/{server}/{session_id}/tags` | Add/remove tags on a session |
| `DELETE` | `/sessions/{server}/{session_id}?confirm=true` | Kill and evict a session |
| `POST` | `/sessions/{server}/{session_id}/collect-logs` | Collect diagnostic logs (returns zip) |

Query params for `GET /sessions/`:
- `?server=<name>` — filter by IxNetwork server
- `?tag=<label>` — filter by tag

### Servers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/servers/` | List all configured IxNetwork servers |
| `POST` | `/servers/` | Add a new server |
| `POST` | `/servers/bulk` | Bulk add/update servers |
| `DELETE` | `/servers/bulk` | Bulk delete servers by name |
| `PATCH` | `/servers/bulk/password` | Set password for multiple servers |
| `PUT` | `/servers/{name}` | Update a server |
| `PATCH` | `/servers/{name}/tags` | Add/remove tags on a server |
| `DELETE` | `/servers/{name}` | Remove a server |
| `POST` | `/servers/{name}/test` | Test connectivity to a server |
| `POST` | `/servers/{name}/probe-web` | Debug IxNetwork Web HTTPS auth probe |

### Poll Control

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/poll/trigger` | Force an immediate poll cycle |
| `GET` | `/poll/status` | Current poller state (last run, next scheduled) |
| `GET` | `/poll/config` | Get current poll interval |
| `PATCH` | `/poll/config` | Update poll interval (10–3600 seconds) |

### Health & Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health/` | Fleet health summary |
| `GET` | `/chassis/` | List all chassis |
| `GET` | `/chassis/{name}/health` | Chassis health detail |
| `GET` | `/metrics` | Prometheus metrics (text/plain) |

## Development

### Format & Lint

```bash
# Format code
black ixse/ tests/

# Lint
ruff check ixse/ tests/ --fix

# Type check
mypy ixse/
```

### Development Server with Auto-reload

```bash
uvicorn ixse.api.main:app --reload
```

## Deployment

See `Dockerfile` for container deployment.

```bash
docker build -t ixse:latest -f Dockerfile .
docker run -p 8080:8080 -v $(pwd)/ixse_config.yaml:/app/ixse_config.yaml ixse:latest
```

## References

- [Project Vision](../project_vision.md)
- [MVP Design](../docs/plans/2026-05-08-ixnetwork-session-explorer-mvp-design.md)
- [RestPy Documentation](https://github.com/OpenIxia/ixnetwork_restpy)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
