"""
Configuration module: YAML loader and Pydantic config models.

Handles loading ixse_config.yaml with environment variable interpolation,
validating IxNetwork server and IxOS chassis definitions.
"""

from typing import Optional
from pydantic import BaseModel


class ServerConfig(BaseModel):
    """REST API server configuration."""
    poll_interval_seconds: int = 30


class IxNetworkServerConfig(BaseModel):
    """IxNetwork server connection parameters."""
    name: str
    host: str
    username: str
    password: str
    tags: list[str] = []


class ChassisConfig(BaseModel):
    """IxOS chassis connection parameters."""
    name: str
    host: str
    username: str
    password: str
    ixnet_server: str
    tags: list[str] = []


class AppConfig(BaseModel):
    """Top-level application configuration."""
    server: ServerConfig
    ixnet_servers: list[IxNetworkServerConfig]
    chassis: list[ChassisConfig]
