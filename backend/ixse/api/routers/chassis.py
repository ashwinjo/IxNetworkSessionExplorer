"""
Chassis endpoints: GET /chassis, GET /chassis/{name}/health.

Provides REST API for listing chassis and querying health metrics.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from ixse.models import ChassisHealth


router = APIRouter(prefix="/chassis", tags=["chassis"])


@router.get("/")
async def list_chassis() -> dict:
    """
    List all chassis with health status.

    Returns:
        Dict with chassis list, including reachability and port counts.
    """
    pass


@router.get("/{name}/health")
async def get_chassis_health(name: str) -> dict:
    """
    Get detailed health for a single chassis.

    Args:
        name: Chassis name

    Returns:
        ChassisHealth object with reachability, latency, and ports in use.
    """
    pass
