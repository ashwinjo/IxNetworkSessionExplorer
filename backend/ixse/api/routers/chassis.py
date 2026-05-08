"""
Chassis endpoints: GET /chassis, GET /chassis/{name}/health.

Provides REST API for listing chassis and querying health metrics.

Note: live IxOS reachability checks are scheduled for a future milestone.
Currently both endpoints return placeholder responses so the frontend and
integration tests can exercise the routing layer without errors.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from ixse.models import ChassisHealth

router = APIRouter(prefix="/chassis", tags=["chassis"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/", summary="List all chassis")
async def list_chassis() -> dict:
    """Return all chassis known to the server.

    Live IxOS health checks will be added in a future milestone.
    """
    return {
        "status": "ok",
        "data": {"chassis": []},
        "timestamp": _now_iso(),
    }


@router.get("/{name}/health", summary="Chassis health detail")
async def get_chassis_health(name: str) -> dict:
    """Return health details for a single chassis.

    Live IxOS reachability checks will be added in a future milestone.
    Returns 404 until chassis config support is implemented.
    """
    raise HTTPException(
        status_code=404,
        detail=f"Chassis '{name}' not found. Chassis management is not yet configured.",
    )
