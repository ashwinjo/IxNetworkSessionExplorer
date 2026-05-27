"""
IxNetwork Web (HTTPS) auth-path probe: standalone vs on-chassis deployment
and reachability (heartbeat) classification.

POST targets (see docs/ixn_auth_types.py):
  - Standalone:  /ixnetworkweb/api/v1/auth/session
  - On-chassis: /platform/api/v2/auth/session
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import requests

from ixse.models import IxNetworkWebSnapshot, ServerEntry

logger = logging.getLogger(__name__)

STANDALONE_AUTH_PATH = "/ixnetworkweb/api/v1/auth/session"
ON_CHASSIS_AUTH_PATH = "/platform/api/v2/auth/session"

IxWebHeartbeat = Literal["green", "yellow", "red"]
IxWebDeployment = Literal["standalone", "onChassis", "windowsClient"]


def _normalize_https_host(host: str) -> tuple[str, int | None]:
    """Parse host string into (hostname, port_or_none). Default HTTPS port is 443."""
    h = (host or "").strip()
    if not h:
        raise ValueError("host must be non-empty")
    if "://" not in h:
        h = "https://" + h
    parsed = urlparse(h)
    if not parsed.hostname:
        raise ValueError(f"could not parse host from {host!r}")
    return parsed.hostname, parsed.port


def _session_url(hostname: str, port: int | None, path: str) -> str:
    if port:
        return f"https://{hostname}:{port}{path}"
    return f"https://{hostname}{path}"


def _probe_https_port(server: ServerEntry, embedded_port: int | None) -> int | None:
    """Port for IxNetwork Web HTTPS auth URLs.

    ``rest_port`` is always treated as the web interface port.  When set it
    takes precedence over any port embedded in ``server.host``; when absent the
    host-embedded port is used; implicit 443 is the final fallback.
    """
    if server.rest_port is not None:
        return int(server.rest_port)
    if embedded_port is not None:
        return embedded_port
    return None  # implies 443


def _auth_payload(username: str, password: str, *, allow_weak_password: bool) -> dict[str, Any]:
    return {
        "username": username,
        "password": password,
        "rememberMe": False,
        "resetWeakPassword": False,
        "ignorePolicy": True,
    }


def _try_auth_post(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    verify_ssl: bool,
) -> tuple[int, dict[str, Any] | None, str | None]:
    try:
        r = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.RequestException as e:
        return -1, None, str(e)
    try:
        body = r.json() if r.content else None
    except ValueError:
        body = None
    return r.status_code, body if isinstance(body, dict) else None, None


def _api_key_from(status: int, body: dict[str, Any] | None) -> str | None:
    if status < 200 or status >= 300 or not body:
        return None
    key = body.get("apiKey")
    if isinstance(key, str) and key:
        return key
    return None


SYSTEM_INFO_PATH = "/ixnetworkweb/api/v2/admin/systeminformation"


def _fetch_ixnetwork_version(
    base_url: str,
    api_key: str,
    *,
    timeout: float,
    verify_ssl: bool,
) -> str | None:
    """GET system info using the obtained apiKey and extract the IxNetwork version.

    Looks for the product entry where ``type == "ixnrest"`` (the core IxNetwork
    engine) and returns its ``version`` string.  Returns None on any error.
    """
    url = base_url + SYSTEM_INFO_PATH
    try:
        r = requests.get(
            url,
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            timeout=timeout,
            verify=verify_ssl,
        )
        if r.status_code < 200 or r.status_code >= 300:
            logger.debug("System info GET %s returned HTTP %s", url, r.status_code)
            return None
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("System info fetch failed for %s: %s", url, exc)
        return None

    for product in data.get("products", []):
        if product.get("type") == "ixnrest":
            version = product.get("version")
            if isinstance(version, str) and version:
                return version
    return None


def _classify_heartbeat(
    s_code: int,
    c_code: int,
    s_key: str | None,
    c_key: str | None,
) -> IxWebHeartbeat:
    if s_key or c_key:
        return "green"
    if s_code == -1 and c_code == -1:
        return "red"
    return "yellow"


def _pick_deployment(
    s_key: str | None,
    c_key: str | None,
    *,
    prefer: IxWebDeployment | None = None,
) -> IxWebDeployment | None:
    if s_key and not c_key:
        return "standalone"
    if c_key and not s_key:
        return "onChassis"
    if s_key and c_key:
        if prefer == "standalone":
            return "standalone"
        return "onChassis"
    return None


def _detail_line(
    s_code: int,
    c_code: int,
    s_err: str | None,
    c_err: str | None,
    heartbeat: IxWebHeartbeat,
) -> str | None:
    if heartbeat == "green":
        return None
    parts = [
        f"standalone path: status={s_code}" + (f" ({s_err})" if s_err else ""),
        f"on-chassis path: status={c_code}" + (f" ({c_err})" if c_err else ""),
    ]
    return "; ".join(parts)


def check_ixnetwork_web(
    server: ServerEntry,
    *,
    timeout: float = 15.0,
    verify_ssl: bool = False,
    prefer: IxWebDeployment | None = None,
) -> IxNetworkWebSnapshot:
    """
    Try both IxNetwork Web auth endpoints; set deployment when auth succeeds.

    Auth payload always includes ``resetWeakPassword=False`` and
    ``ignorePolicy=True`` to bypass IxNetwork password-policy enforcement
    that would otherwise block API auth even with valid credentials.

    HTTPS target uses ``server.rest_port`` when set (same REST Port as the
    server form); otherwise host-embedded port or 443.

    Heartbeat:
      - green: at least one path returned a usable apiKey
      - red: both paths failed at the network layer
      - yellow: HTTP responses but no successful auth, or mixed failure modes
    """
    checked_at = datetime.now(timezone.utc)
    try:
        hostname, embedded_port = _normalize_https_host(server.host)
    except ValueError as exc:
        return IxNetworkWebSnapshot(
            deployment=None,
            heartbeat="yellow",
            auth_path=None,
            detail=str(exc),
            checked_at=checked_at,
        )

    port = _probe_https_port(server, embedded_port)

    payload = _auth_payload(server.username, server.password, allow_weak_password=True)

    standalone_url = _session_url(hostname, port, STANDALONE_AUTH_PATH)
    chassis_url = _session_url(hostname, port, ON_CHASSIS_AUTH_PATH)

    s_code, s_body, s_err = _try_auth_post(
        standalone_url, payload, timeout=timeout, verify_ssl=verify_ssl
    )
    c_code, c_body, c_err = _try_auth_post(
        chassis_url, payload, timeout=timeout, verify_ssl=verify_ssl
    )

    s_key = _api_key_from(s_code, s_body)
    c_key = _api_key_from(c_code, c_body)

    heartbeat = _classify_heartbeat(s_code, c_code, s_key, c_key)
    deployment = _pick_deployment(s_key, c_key, prefer=prefer)

    ixnetwork_version: str | None = None

    if heartbeat == "green":
        winning_key = s_key or c_key
        if deployment == "standalone":
            auth_path = STANDALONE_AUTH_PATH
        elif deployment == "onChassis":
            auth_path = ON_CHASSIS_AUTH_PATH
        else:
            auth_path = None
        detail = None
        # Fetch IxNetwork product version using the obtained API key
        base_url = _session_url(hostname, port, "").rstrip("/")
        ixnetwork_version = _fetch_ixnetwork_version(
            base_url, winning_key, timeout=timeout, verify_ssl=verify_ssl  # type: ignore[arg-type]
        )
    else:
        auth_path = None
        detail = _detail_line(s_code, c_code, s_err, c_err, heartbeat)

    logger.info(
        "IxNetwork Web probe '%s': heartbeat=%s deployment=%s version=%s standalone=[%s] chassis=[%s]",
        server.name,
        heartbeat,
        deployment,
        ixnetwork_version or "—",
        f"HTTP {s_code}" if s_code != -1 else f"ERR {s_err}",
        f"HTTP {c_code}" if c_code != -1 else f"ERR {c_err}",
    )

    return IxNetworkWebSnapshot(
        deployment=deployment,
        heartbeat=heartbeat,
        auth_path=auth_path,
        detail=detail,
        checked_at=checked_at,
        ixnetwork_version=ixnetwork_version,
    )


def probe_web_verbose(
    server: ServerEntry,
    *,
    timeout: float = 15.0,
    verify_ssl: bool = False,
) -> dict[str, Any]:
    """Run the HTTPS auth probe and return full debug detail.

    Returns a dict with:
      - ``standalone_url``  / ``chassis_url``   — exact URLs tried
      - ``standalone_status`` / ``chassis_status`` — HTTP codes (-1 = network error)
      - ``standalone_error``  / ``chassis_error``  — error strings when code == -1
      - ``standalone_got_key`` / ``chassis_got_key`` — whether an apiKey was received
      - ``standalone_body_keys`` / ``chassis_body_keys`` — top-level keys in response body
      - ``heartbeat``, ``deployment``, ``detail``  — same as IxNetworkWebSnapshot
    """
    checked_at = datetime.now(timezone.utc)
    try:
        hostname, embedded_port = _normalize_https_host(server.host)
    except ValueError as exc:
        return {
            "error": str(exc),
            "standalone_url": None,
            "chassis_url": None,
            "heartbeat": "yellow",
            "deployment": None,
        }

    port = _probe_https_port(server, embedded_port)
    payload = _auth_payload(server.username, server.password, allow_weak_password=True)

    standalone_url = _session_url(hostname, port, STANDALONE_AUTH_PATH)
    chassis_url = _session_url(hostname, port, ON_CHASSIS_AUTH_PATH)

    s_code, s_body, s_err = _try_auth_post(
        standalone_url, payload, timeout=timeout, verify_ssl=verify_ssl
    )
    c_code, c_body, c_err = _try_auth_post(
        chassis_url, payload, timeout=timeout, verify_ssl=verify_ssl
    )

    s_key = _api_key_from(s_code, s_body)
    c_key = _api_key_from(c_code, c_body)

    heartbeat = _classify_heartbeat(s_code, c_code, s_key, c_key)
    deployment = _pick_deployment(s_key, c_key)
    detail = _detail_line(s_code, c_code, s_err, c_err, heartbeat) if heartbeat != "green" else None

    ixnetwork_version: str | None = None
    system_info_url: str | None = None
    if heartbeat == "green":
        winning_key = s_key or c_key
        base_url = _session_url(hostname, port, "").rstrip("/")
        system_info_url = base_url + SYSTEM_INFO_PATH
        ixnetwork_version = _fetch_ixnetwork_version(
            base_url, winning_key, timeout=timeout, verify_ssl=verify_ssl  # type: ignore[arg-type]
        )

    return {
        "checked_at": checked_at.isoformat(),
        "standalone_url": standalone_url,
        "chassis_url": chassis_url,
        "standalone_status": s_code,
        "standalone_error": s_err,
        "standalone_got_key": s_key is not None,
        "standalone_body_keys": sorted(s_body.keys()) if isinstance(s_body, dict) else None,
        "chassis_status": c_code,
        "chassis_error": c_err,
        "chassis_got_key": c_key is not None,
        "chassis_body_keys": sorted(c_body.keys()) if isinstance(c_body, dict) else None,
        "heartbeat": heartbeat,
        "deployment": deployment,
        "detail": detail,
        "system_info_url": system_info_url,
        "ixnetwork_version": ixnetwork_version,
    }
