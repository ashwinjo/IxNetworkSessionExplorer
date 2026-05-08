"""
IxNetwork Session Explorer - unified session manager for lab administrators.

Core library for discovering and tracking IxNetwork sessions across multiple servers.
"""

__version__ = "0.1.0"
__author__ = "Network Automation Team"

# Re-export key models for convenience
from ixse.models import PlaneStatus, Session, SessionPort

__all__ = [
    "Session",
    "SessionPort",
    "PlaneStatus",
]
