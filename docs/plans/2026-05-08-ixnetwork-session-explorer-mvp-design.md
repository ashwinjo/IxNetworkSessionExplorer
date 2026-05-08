# IxNetworkSessionExplorer MVP Design

**Date:** 2026-05-08
**Status:** Approved
**Scope:** Standalone web app for unified IxNetwork session management

---

## Problem & Motivation

Lab administrators lack visibility into active IxNetwork sessions across multiple servers. Today: manual login to each server. Need: unified view of session state + utilization (control plane + data plane).

---

## MVP Scope

**Include:**
- Multi-server session discovery
- Control plane (CP) + Data plane (DP) utilization detection
- Session tagging + deletion
- YAML configuration (multi-server support)
- SQLite persistence (decouples polling from UI)
- Standalone web UI (vanilla HTML/JS)

**Exclude (Phase 2+):**
- Prometheus metrics export
- `/chassis` endpoints (reuse existing Ixia Inventory)
- Advanced filtering/sorting
- User authentication

---

## Architecture

```
IxNetworkSessionExplorer/
├── backend/
│   ├── ixse/
│   │   ├── config.py           # YAML config loader
│   │   ├── client.py           # RestPy abstraction (IxNetwork API)
│   │   ├── ixos.py             # IxOS REST abstraction (port stats)
│   │   ├── models.py           # Pydantic models (Session, Port, PlaneStatus)
│   │   ├── plane.py            # CP/DP detection logic
│   │   └── api/
│   │       ├── main.py         # FastAPI app + background poller
│   │       ├── state.py        # SQLite persistence layer
│   │       └── routers/
│   │           └── sessions.py # Session CRUD endpoints
│   ├── pyproject.toml
│   ├── ixse_config.yaml        # Example config
│   ├── Dockerfile
│   ├── requirements.txt        # Python deps
│   └── tests/
│       └── test_api.py         # Basic integration tests
│
├── frontend/
│   ├── index.html              # Single-page app
│   ├── app.js                  # Fetch + DOM logic
│   ├── style.css               # Basic styling
│   └── config.js               # API base URL (localhost:8080)
│
└── docs/plans/
    └── 2026-05-08-ixnetwork-session-explorer-mvp-design.md
```

---

## Data Flow

### Backend Poller (Async)

```
Every 60 seconds:
1. Load ixse_config.yaml (servers list)
2. For each server:
   a. Connect via RestPy
   b. List all sessions
   c. For each session:
      - Detect CP: check Topology.DeviceGroup.SessionStatus
      - Detect DP: query IxOS REST for port TX/RX stats
      - Compute utilized = CP AND DP
   d. Write to SQLite (session_id, name, server, ports, cp_active, dp_active, utilized, tags, last_polled_at)
3. Update in-memory cache (fast API reads)
```

### Frontend Refresh (Independent)

```
User toggles auto-refresh ON:
- Every 30s: fetch GET /sessions from backend
- Display table + last_polled timestamp

User clicks [Refresh Now]:
- POST /poll/trigger (force immediate poll in backend)
- Wait for response
- Fetch GET /sessions
- Update table
```

**Decoupling:** Poller runs continuously. UI fetches on its own schedule. No dependency.

---

## API Endpoints (MVP)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/sessions` | List all sessions. Optional filters: `?server=`, `?chassis=`, `?utilized=true` |
| GET | `/sessions/{server}/{id}` | Full session detail (ID, name, ports, CP, DP, tags, last_polled) |
| PATCH | `/sessions/{server}/{id}/tags` | Add/remove tags. Body: `{"action": "add", "tag": "bgp"}` |
| DELETE | `/sessions/{server}/{id}?confirm=true` | Kill session (calls RestPy to remove) |
| POST | `/poll/trigger` | Force immediate poll. Returns fresh `/sessions` data + timestamp |
| GET | `/poll/status` | Last poll time + next scheduled poll time |

### Response Schema

**GET /sessions:**
```json
{
  "servers": [
    {
      "name": "ixnet-server-01",
      "host": "10.1.1.100",
      "session_count": 3,
      "sessions": [
        {
          "id": "session-123",
          "name": "bgp-01",
          "server": "ixnet-server-01",
          "chassis": ["lab-01", "lab-02"],
          "ports": ["1/1", "1/2", "2/1"],
          "cp_active": true,
          "dp_active": true,
          "utilized": true,
          "tags": ["bgp", "production"],
          "last_polled": "2026-05-08T12:34:56Z"
        }
      ]
    }
  ],
  "timestamp": "2026-05-08T12:34:56Z"
}
```

---

## Frontend UI Design

### Layout

```
╔════════════════════════════════════════════════════════╗
║     IxNetwork Session Explorer                         ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║  Last polled: 2026-05-08 12:34:56                     ║
║  [Refresh Now]  [Expand All] [Collapse All]          ║
║  Auto-refresh: [Toggle ON/OFF]                        ║
║                                                        ║
║  Search: [_____________________]                      ║
║  (filter servers by IP or name, real-time)            ║
║                                                        ║
╠════════════════════════════════════════════════════════╣
║                                                        ║
║  ixnet-server-01 (10.1.1.100)  [▼]  3 sessions       ║
║  ├─ bgp-01    | lab-01     | 1/1,1/2 | Y│Y│✓          ║
║  │  [Details] [Tag] [Kill]                            ║
║  ├─ ospf-02   | lab-02     | 2/1     | Y│N│✗          ║
║  │  [Details] [Tag] [Kill]                            ║
║  └─ idle-03   | lab-01,03  | 3/1,4/1 | N│N│✗          ║
║     [Details] [Tag] [Kill]                            ║
║                                                        ║
║  ixnet-server-02 (10.1.1.101)  [▶]  2 sessions       ║
║                                                        ║
╚════════════════════════════════════════════════════════╝
```

### Features

- **Collapsible servers:** Click row to expand/collapse sessions
- **Search filter:** Real-time filter servers by IP or name (case-insensitive)
- **[Expand All] / [Collapse All]:** Bulk open/close all servers
- **Per-session table:** SESSION | CHASSIS | PORTS | CP_ACTIVE | DP_ACTIVE | UTILIZED
- **Per-session actions:**
  - `[Details]` → modal showing full info (ID, name, ports, tags, last_polled)
  - `[Tag]` → modal: enter tag, click "Add" or "Remove"
  - `[Kill]` → confirm dialog, DELETE to backend
- **[Refresh Now]** → POST /poll/trigger, fetch fresh data, update table
- **Auto-refresh toggle** → if ON, fetch every 30s; if OFF, manual only
- **Timestamp display** → "Last polled: {time}" updated on each fetch

### Technology

- **HTML:** Single page (`index.html`)
- **JavaScript:** Vanilla JS (no frameworks). `fetch()` API for HTTP. DOM manipulation for table + modals.
- **CSS:** Basic styling (table, buttons, modals, search box)
- **Config:** `config.js` with `API_BASE_URL = "http://localhost:8080"`

---

## Backend Implementation Details

### Config (YAML)

**File:** `ixse_config.yaml`

```yaml
poller:
  interval_seconds: 60

ixnet_servers:
  - name: ixnet-server-01
    host: 10.1.1.100
    username: admin
    password: ${IXNET_PASSWORD}       # Interpolated from env at startup

  - name: ixnet-server-02
    host: 10.1.1.101
    username: admin
    password: ${IXNET_PASSWORD_2}
```

**Env vars:** Set before running:
```bash
export IXNET_PASSWORD="Kimchi123Kimchi123!"
export IXNET_PASSWORD_2="OtherPassword"
```

Backend loads config at startup, validates creds are present (not lazy).

### Models (Pydantic)

```python
class SessionPort:
    chassis_name: str   # e.g. "lab-01"
    card: int          # 1-24
    port: int          # 1-4

class PlaneStatus:
    cp_active: bool    # control plane (protocols) started?
    dp_active: bool    # data plane (traffic) running?

class Session:
    id: str
    name: str
    ixnet_server: str
    ports: list[SessionPort]
    cp_active: bool
    dp_active: bool
    tags: list[str]
    last_polled: datetime

class PollStatus:
    last_polled_at: datetime
    next_scheduled: datetime
```

### Detection Logic

**Control Plane (CP):**
```python
def detect_cp(session_obj) -> bool:
    """Check if protocols started via RestPy"""
    topologies = session_obj.Topology.find()
    for topo in topologies:
        device_groups = topo.DeviceGroup.find()
        for dg in device_groups:
            if dg.SessionStatus != "notStarted":
                return True
    return False
```

**Data Plane (DP):**
```python
def detect_dp(chassis_host, ports: list[SessionPort]) -> bool:
    """Check if traffic running via IxOS REST"""
    for port in ports:
        url = f"http://{chassis_host}/api/v1/ixos/ports/{port.card}/{port.port}/stats"
        stats = requests.get(url, auth=(user, pwd)).json()
        if stats.get("txFrames", 0) > 0 or stats.get("rxFrames", 0) > 0:
            return True
    return False
```

**Utilization:**
```python
utilized = cp_active and dp_active
```

### Poller Task (Async)

```python
# In api/main.py
async def background_poller():
    while True:
        await asyncio.sleep(config.poller.interval_seconds)
        try:
            for server_config in config.ixnet_servers:
                # Connect, list sessions, detect CP/DP, store in SQLite
                # Update in-memory cache
        except Exception as e:
            logger.error(f"Poller error: {e}")
            # Continue on next iteration (resilient)
```

### SQLite Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    name TEXT,
    ixnet_server TEXT,
    ports TEXT,              -- JSON list
    cp_active INTEGER,       -- 0/1
    dp_active INTEGER,       -- 0/1
    tags TEXT,               -- JSON list
    last_polled_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_server ON sessions(ixnet_server);
CREATE INDEX idx_last_polled ON sessions(last_polled_at);
```

---

## Error Handling

- **Config load fails** → exit at startup (fail fast)
- **Poller hits unreachable server** → log error, skip server, continue next iteration
- **RestPy/IxOS API timeout** → 10s timeout per request, retry once, then skip
- **Session kill fails** → return error response to frontend, user sees error message
- **Malformed tag input** → validate on backend, return 400 Bad Request

---

## Testing Strategy (MVP)

- **Unit tests:** Config loading, plane detection logic (mock RestPy/IxOS)
- **Integration tests:** FastAPI endpoints (in-memory SQLite, mock poller)
- **Manual testing:** Real IxNetwork server (10.36.236.121)

---

## Deployment

### Docker (Backend)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ixse /app/ixse
COPY ixse_config.yaml /app/

EXPOSE 8080

CMD ["uvicorn", "ixse.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Build & run:
```bash
docker build -t ixse:latest -f backend/Dockerfile .
docker run -p 8080:8080 -v $(pwd)/ixse_config.yaml:/app/ixse_config.yaml ixse:latest
```

### Frontend (Static)

Serve `frontend/index.html` via simple HTTP server:
```bash
cd frontend
python -m http.server 3000
# Open http://localhost:3000
```

---

## Success Criteria

- ✅ Backend API runs, responds to `/sessions` within 1s
- ✅ Poller queries 10.36.236.121 successfully, detects CP/DP, stores in SQLite
- ✅ Frontend loads, displays server list + session table
- ✅ [Details], [Tag], [Kill] buttons work end-to-end
- ✅ Search filter works (real-time)
- ✅ [Refresh Now] triggers immediate poll + updates UI
- ✅ Auto-refresh toggle fetches every 30s when ON
- ✅ Timestamps shown (last polled time)

---

## Known Limitations (Phase 1)

- No user authentication (localhost only)
- No persistent session tags (tags lost on server restart)
- No SSL/TLS (HTTP only)
- No advanced filtering/sorting
- No metrics export (Phase 2)
- Single database file (no clustering)

---

## Next Steps (Phase 2)

- Persistent tag storage (database)
- Prometheus metrics export
- Multi-user support + auth
- Alert thresholds (e.g., "alert if 5+ sessions utilized")
- Historical data (trend analysis)
- Chart/visualization of utilization over time

---

## References

- Project Vision: [`project_vision.md`](../../project_vision.md)
- CLAUDE.md: Architecture + patterns
- RestPy Docs: https://github.com/OpenIxia/ixnetwork_restpy
- FastAPI: https://fastapi.tiangolo.com/
- Vanilla JS Fetch: https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API
