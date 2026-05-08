"""
FastAPI application: REST server with background polling.

Exposes endpoints for session management, chassis monitoring, and health checks.
Runs a background task that polls all IxNetwork servers every poll_interval_seconds.
Integrates metrics export for Prometheus.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Sets up routes, background tasks, and middleware.

    Returns:
        Configured FastAPI app instance.
    """
    app = FastAPI(title="IxNetworkSessionExplorer", version="0.1.0")
    return app


async def poll_fleet():
    """
    Background polling task.

    Runs every poll_interval_seconds (configurable).
    Queries all IxNetwork servers and chassis, updates in-memory state.
    """
    pass


async def startup_event():
    """Called on app startup."""
    pass


async def shutdown_event():
    """Called on app shutdown."""
    pass
