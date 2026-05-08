"""
Configuration module: YAML loader and Pydantic config models.

Handles loading ixse_config.yaml with environment variable interpolation,
validating IxNetwork server definitions.

Public API:
    ConfigError   — raised on any configuration problem
    load_config() — load, interpolate, and validate a YAML config file
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError, field_validator


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """
    Raised on any configuration failure.

    Attributes:
        message — human-readable description of what failed and what to do
    """


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class IxNetServerConfig(BaseModel):
    """IxNetwork server connection parameters."""

    name: str
    host: str
    username: str
    password: str  # resolved from env at load time
    rest_port: int | None = None  # None = let RestPy auto-detect (tries 11009 then 443)

    @field_validator("name", "host", "username", "password", mode="before")
    @classmethod
    def must_be_non_empty(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            raise ValueError("must not be empty")
        return v


class PollerConfig(BaseModel):
    """Background poller configuration."""

    interval_seconds: int = 60


class AppConfig(BaseModel):
    """Top-level application configuration."""

    poller: PollerConfig = PollerConfig()
    ixnet_servers: list[IxNetServerConfig]

    @field_validator("ixnet_servers", mode="before")
    @classmethod
    def servers_must_not_be_empty(cls, v: Any) -> Any:
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("at least one ixnet_server entry is required")
        return v


# ---------------------------------------------------------------------------
# Environment variable interpolation
# ---------------------------------------------------------------------------

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_INVALID_VAR_PATTERN = re.compile(r"\$\{([^}]*)\}")


def _interpolate_string(value: str, config_path: Path) -> str:
    """
    Replace all ${VAR_NAME} markers in *value* with their environment values.

    Variable names must match [A-Z_][A-Z0-9_]* (uppercase, digits, underscores).
    Raises ConfigError immediately if any referenced variable is unset or if
    a ${...} marker contains an invalid variable name.
    """
    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved is None:
            raise ConfigError(
                f"Environment variable '{var_name}' is not set, "
                f"but is required by config file: {config_path}\n"
                f"Fix: export {var_name}=<value> before starting ixse."
            )
        return resolved

    result = _ENV_VAR_PATTERN.sub(replacer, value)
    # Check for remaining ${...} that didn't match the strict pattern (invalid var name syntax)
    invalid = _INVALID_VAR_PATTERN.findall(result)
    if invalid:
        raise ConfigError(
            f"Invalid environment variable syntax in config {config_path}: "
            f"'${{{invalid[0]}}}' — variable names must match [A-Z_][A-Z0-9_]*"
        )
    return result


def _interpolate_value(value: Any, config_path: Path) -> Any:
    """Recursively walk the parsed YAML structure and interpolate all strings."""
    if isinstance(value, str):
        return _interpolate_string(value, config_path)
    if isinstance(value, dict):
        return {k: _interpolate_value(v, config_path) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_value(item, config_path) for item in value]
    # int, float, bool, None — pass through unchanged
    return value


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> AppConfig:
    """
    Load and validate config from a YAML file. Fails fast on any error.

    Steps:
      1. Read file (ConfigError if not found)
      2. Parse YAML (ConfigError if malformed)
      3. Interpolate ${VAR_NAME} env vars (ConfigError if any var is unset)
      4. Validate with Pydantic (ConfigError if schema violated)

    Returns:
        AppConfig — fully validated, env-resolved configuration object

    Raises:
        ConfigError — on any of the above failure modes
    """
    config_path = Path(path)

    # Step 1: read file
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"Config file not found: {config_path}\n"
            f"Fix: create the file or pass a correct --config path."
        )
    except OSError as exc:
        raise ConfigError(
            f"Could not read config file: {config_path}\n"
            f"OS error: {exc}"
        )

    # Step 2: parse YAML
    try:
        raw_data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Failed to parse YAML config: {config_path}\n"
            f"YAML error: {exc}"
        )

    if raw_data is None:
        raise ConfigError(
            f"Config file is empty: {config_path}\n"
            f"Fix: populate it with at least an ixnet_servers block."
        )

    if not isinstance(raw_data, dict):
        raise ConfigError(
            f"Config file must be a YAML mapping (dict) at the top level: {config_path}\n"
            f"Got: {type(raw_data).__name__}"
        )

    # Step 3: interpolate env vars (fail fast — raises ConfigError on first missing var)
    interpolated = _interpolate_value(raw_data, config_path)

    # Step 4: Pydantic validation
    try:
        return AppConfig(**interpolated)
    except ValidationError as exc:
        # Translate Pydantic's error into a ConfigError with the file path
        details = "; ".join(
            f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        raise ConfigError(
            f"Config validation failed for: {config_path}\n"
            f"Errors: {details}\n"
            f"Fix: check the field(s) listed above in your config file."
        )
    except TypeError as exc:
        raise ConfigError(
            f"Unexpected config structure in: {config_path}\n"
            f"Error: {exc}"
        )
