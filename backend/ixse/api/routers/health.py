"""
Health endpoints: GET /health.

Provides REST API for fleet-wide health checks and reachability status.

Note: full health-check implementation (live RestPy ping) is scheduled for
a future milestone.  The endpoint currently returns a static "ok" envelope
so downstream clients and the frontend can poll without errors.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/", summary="Fleet health summary")
async def get_fleet_health() -> dict:
    """Return a fleet-wide health summary.

    Live reachability checks will be added in a future milestone.
    Currently returns a static ``ok`` envelope.
    """
    return {
        "status": "ok",
        "data": {"servers": [], "chassis": []},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
