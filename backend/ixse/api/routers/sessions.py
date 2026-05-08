"""
Sessions endpoints: GET /sessions, PATCH tags, DELETE session.

Provides REST API for listing, filtering, tagging, and destroying
IxNetwork sessions.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from ixse.models import Session


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/")
async def list_sessions(
    server: Optional[str] = Query(None, description="Filter by server name"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
) -> dict:
    """
    List all sessions with optional filters.

    Args:
        server: Filter to sessions on specific IxNetwork server
        tag: Filter to sessions with specific tag

    Returns:
        Dict with sessions list and metadata.
    """
    pass


@router.get("/{server}/{session_id}")
async def get_session_detail(server: str, session_id: str) -> dict:
    """
    Get full details for a single session.

    Args:
        server: IxNetwork server name
        session_id: Session ID on that server

    Returns:
        Session object with ports, plane status, and tags.
    """
    pass


@router.patch("/{server}/{session_id}/tags")
async def update_session_tags(server: str, session_id: str, body: dict) -> dict:
    """
    Add or remove tags on a session.

    Args:
        server: IxNetwork server name
        session_id: Session ID
        body: JSON with "add" and/or "remove" lists of tag strings

    Returns:
        Updated session object.
    """
    pass


@router.delete("/{server}/{session_id}")
async def delete_session(server: str, session_id: str, confirm: bool = False) -> dict:
    """
    Destroy a session (kill it on the server).

    Args:
        server: IxNetwork server name
        session_id: Session ID to destroy
        confirm: Must be True to confirm deletion

    Returns:
        Status message.
    """
    pass
