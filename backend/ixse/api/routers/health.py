"""
Health endpoints: GET /health.

Provides REST API for fleet-wide health checks and reachability status.
"""

from fastapi import APIRouter


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
async def get_fleet_health() -> dict:
    """
    Get health status for all IxNetwork servers and chassis.

    Returns:
        Dict with "servers" and "chassis" sections, each listing reachability.
    """
    pass
